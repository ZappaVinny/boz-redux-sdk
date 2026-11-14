"""The Game tab's rules (synthetic): rounds, special rounds, zombie looks, economy, runtime."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import game, group, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402


def level_body(sp, mp, looks):
    owner = game.LEVEL
    props = [
        reflect.Property(owner, iw_hash('std::list<unsigned int>'), iw_hash('m_StartingWavesSP'),
                         struct.pack(f'<I{len(sp)}I', len(sp), *sp)),
        reflect.Property(owner, iw_hash('std::list<unsigned int>'), iw_hash('m_StartingWavesMP'),
                         struct.pack(f'<I{len(mp)}I', len(mp), *mp)),
        reflect.Property(owner, iw_hash('std::vector<unsigned int>'), iw_hash('m_zombiesConfigurations'),
                         struct.pack(f'<I{len(looks)}I', len(looks), *looks)),
    ]
    return resources.encode_reflected(reflect.Blob(owner, props))


def look_body(models):
    owner = game.ZOMBIE_CONFIG
    return resources.encode_reflected(reflect.Blob(owner, [
        reflect.Property(owner, iw_hash('unsigned int'), iw_hash('m_skel'), struct.pack('<I', 7)),
        reflect.Property(owner, iw_hash('std::vector<unsigned int>'), iw_hash('LOD0'),
                         struct.pack(f'<I{len(models)}I', len(models), *models))]))


def box_spec(cost):
    blob = reflect.Blob(iw_hash('CMysteryBox'), [
        reflect.Property(iw_hash('CMysteryBox'), iw_hash('unsigned int'), iw_hash('m_Cost'),
                         struct.pack('<I', cost))])
    component = resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CMysteryBox'), [blob])
    return resources.encode_entity_spec(resources.EntitySpec([component]))


def statics():
    """A level with one chain shared by every game: two rounds, then one that repeats."""
    first, second, last = iw_hash('wave1'), iw_hash('wave2'), iw_hash('wave3')
    waves = [
        (game.WAVE_CLASSES[0], first, {'class': 'CWave', 'm_ZombieCount': 6, 'm_MaxActive': 6,
                                        'm_ZombieHealth': 150}, second),
        (game.WAVE_CLASSES[0], second, {'class': 'CWave', 'm_ZombieCount': 10, 'm_MaxActive': 8,
                                         'm_ZombieHealth': 250}, last),
        (game.WAVE_CLASSES[1], last, {'class': 'CWaveRepeatable', 'm_ZombieCount': 20,
                                       'm_MaxActive': 10, 'm_ZombieCountMultiplier': 1.5,
                                       'm_ZombieHealth': 300, 'm_ZombieHealthMultiplier': 2.0,
                                       'm_StartingWave': 3}, 0),
        (game.WAVE_CLASSES[2], iw_hash('dogs'), {'class': 'CWaveSpeciality', 'm_HellhoundWave': True,
                                                  'm_players2ZombieNumber': [6, 12, 16, 18],
                                                  'm_ZombieTypes': [iw_hash('zombie_dog')], 'm_healthBase': [300],
                                                  'm_waveType': 1, 'm_MaxActive': 3}, 0),
    ]
    wave_type = group.ResourceType(game.WAVE, 0, 1, [
        group.Resource(iw_hash(cls), key, game.encode_wave(data, nxt)) for cls, key, data, nxt in waves])
    looks = [iw_hash('look_a'), iw_hash('look_b')]
    types = [
        group.ResourceType(game.LEVEL, 1, 1, [group.Resource(None, iw_hash('MYMAP'),
                                                             level_body([first] * 3, [first] * 3, looks))]),
        wave_type,
        group.ResourceType(game.ZOMBIE_CONFIG, 1, 1, [
            group.Resource(None, looks[0], look_body([1, 2])), group.Resource(None, looks[1], look_body([3]))]),
        group.ResourceType(resources.ENTITY_SPEC, 1, 1, [
            group.Resource(None, iw_hash('box_stock'), box_spec(950)),
            group.Resource(None, iw_hash('box_own'), box_spec(400))]),
    ]
    return group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), [group.Section(group.RESOURCES, b'', types)])


class Rounds(unittest.TestCase):
    def test_read_follows_each_chain(self):
        rounds = game.read_rounds(statics())
        self.assertEqual(sorted(rounds['chains']), sorted(game.CHAIN_KEYS))
        normal = rounds['chains']['normal']
        self.assertEqual([w['m_ZombieCount'] for w in normal], [6, 10, 20])
        self.assertEqual(normal[0]['m_StartingTimer'], 1000)            # a default filled in
        self.assertEqual(rounds['specials'][0]['m_players2ZombieNumber'], [6, 12, 16, 18])

    def test_base_rounds_untouched_without_changes(self):
        self.assertFalse(game.changes_rounds({'sets': [], 'modes': game.default_modes()}))
        level = statics()
        before = group.encode(level)
        with tempfile.TemporaryDirectory() as temp:
            game.apply({'rounds': {'sets': [], 'modes': game.default_modes()}}, Path(temp),
                       {'mymap_statics.group.bin': level}, 'mymap')
        self.assertEqual(group.encode(level), before)

    def test_a_set_for_some_modes_the_base_for_the_rest(self):
        level = statics()
        base = game.read_rounds(level)
        harder = game.normalize_set({'name': 'Harder', 'from': 'normal',
                                     'rounds': [dict(w, m_ZombieCount=w['m_ZombieCount'] * 2)
                                                for w in base['chains']['normal']],
                                     'specials': [{k: v for k, v in base['specials'][0].items() if k != 'm_waveType'}]})
        modes = game.default_modes()
        modes['coop2'] = {'set': 'Harder', 'zombies': 1.0, 'health': 1.0}
        modes['hard'] = {'set': '', 'zombies': 1.5, 'health': 2.0}
        repeating = game.write_rounds(level, {'sets': [harder], 'modes': modes})
        again = game.read_rounds(group.parse(group.encode(level)))
        self.assertEqual([w['m_ZombieCount'] for w in again['chains']['coop2']], [12, 20, 40])
        self.assertEqual([w['m_ZombieCount'] for w in again['chains']['normal']], [6, 10, 20])  # the base
        self.assertEqual([w['m_ZombieCount'] for w in again['chains']['hard']], [9, 15, 30])
        self.assertEqual([w['m_ZombieHealth'] for w in again['chains']['hard']], [300, 500, 600])
        self.assertEqual(again['chains']['coop2'][-1]['class'], 'CWaveRepeatable')
        # coop2 has the set's dog round; normal (base, m_waveType 1) keeps the base's.
        types = sorted(int(w['m_waveType']) for w in again['specials'])
        self.assertEqual(types, [1, 3])
        # hard's repeating round: the game's formula times 2.
        self.assertEqual(repeating, {iw_hash('boz_hard_3'): {'grow': False, 'scale': 2.0}})
        names = {r.in_group_hash for t in level.types() if t.class_hash == game.WAVE for r in t.resources}
        self.assertIn(iw_hash('boz_coop2_s1'), names)
        self.assertNotIn(iw_hash('wave1'), names)

    def test_old_chains_become_sets(self):
        base = game.read_rounds(statics())
        chains = {k: [dict(w) for w in base['chains']['normal']] for k in game.CHAIN_KEYS}
        chains['easy'][0]['m_ZombieHealth'] = 75
        specials = [dict(base['specials'][0], m_waveType=1), dict(base['specials'][0], m_waveType=0, m_chance=7)]
        data = game.upgrade({'rounds': {'chains': chains, 'specials': specials, 'repeat_health': 'grow'}})
        sets = {s['name']: s for s in data['rounds']['sets']}
        # Normal has a dog round, hard and co-op none: three sets, nothing lost.
        self.assertEqual(sorted(sets), ['Easy', 'Hard', 'Standard'])
        self.assertEqual(data['rounds']['modes']['coop4']['set'], 'Hard')
        self.assertEqual(data['rounds']['modes']['normal']['set'], 'Standard')
        self.assertEqual(data['rounds']['modes']['easy']['set'], 'Easy')
        self.assertEqual(sets['Easy']['specials'][0]['m_chance'], 7)
        self.assertNotIn('m_waveType', sets['Standard']['specials'][0])
        self.assertEqual(sets['Standard']['after_health'], 'grow')
        self.assertEqual(game.check(data), [])

    def test_copies_of_the_base_fold_back(self):
        base = game.read_rounds(statics())
        chains = {k: [dict(w) for w in base['chains'][k]] for k in game.CHAIN_KEYS}
        chains['coop4'][0]['m_ZombieCount'] = 99
        specials = [dict(w) for w in base['specials']]
        data = game.simplify(game.upgrade({'rounds': {'chains': chains, 'specials': specials}}), base)
        modes = data['rounds']['modes']
        self.assertEqual(modes['coop4']['set'], 'Co-op 4')
        self.assertTrue(all(modes[k]['set'] == '' for k in game.CHAIN_KEYS if k != 'coop4'))
        self.assertEqual([s['name'] for s in data['rounds']['sets']], ['Co-op 4'])
        own = {'sets': [game.normalize_set({'name': 'Mine', 'from': 'normal', 'rounds': base['chains']['normal']})],
               'modes': dict(game.default_modes(), normal={'set': 'Mine', 'zombies': 1.0, 'health': 1.0})}
        kept = game.simplify({'rounds': own}, base)['rounds']
        self.assertEqual((kept['modes']['normal']['set'], len(kept['sets'])), ('Mine', 1))   # a new set stays

    def test_summary(self):
        self.assertEqual(game.summary({}), "the base map's rounds")
        modes = {k: {'set': 'Standard', 'zombies': 1.0, 'health': 1.0} for k in game.CHAIN_KEYS}
        data = {'rounds': {'sets': [{'name': 'Standard', 'rounds': [{}], 'specials': [{}, {}]}], 'modes': modes},
                'economy': {'cvars': {'StartingScore': 900}}}
        self.assertEqual(game.summary(data), 'Standard rounds for all modes, 2 special rounds, 1 setting changed')
        modes['coop4'] = {'set': '', 'zombies': 2.0, 'health': 1.0}
        self.assertEqual(game.summary(data).split(', 2 special')[0],
                         "Standard rounds: solo easy, solo normal, solo hard, co-op 2, co-op 3; "
                         "the base map's (zombies x2) rounds: co-op 4")

    def test_round_values_like_the_game(self):
        chain = game.read_rounds(statics())['chains']['normal']
        self.assertEqual(game.round_values(chain, 1)['zombies'], 6)
        self.assertEqual(game.round_values(chain, 3)['zombies'], 20)        # not past its start yet
        self.assertEqual(game.round_values(chain, 5)['zombies'], 45)        # 20 x 1.5^2
        self.assertEqual(game.round_values(chain, 5)['health'], 100)        # the game's 10 x 25 - 150
        self.assertEqual(game.round_values(chain, 5, grow_health=True)['health'], 1200)
        self.assertEqual(game.round_values(chain, 2)['health'], 250)

    def test_check(self):
        base = game.read_rounds(statics())
        broken = game.normalize_set({'name': 'Mine', 'rounds': [dict(base['chains']['normal'][0], m_MaxActive=0)],
                                     'specials': [dict(base['specials'][0], m_minNormalWavesInterval=9,
                                                       m_maxNormalWavesInterval=2)]})
        modes = game.default_modes()
        modes['easy'] = {'set': 'Gone', 'zombies': 1.0, 'health': 50.0}
        problems = game.check({'rounds': {'sets': [broken, dict(broken)], 'modes': modes},
                               'economy': {'cvars': {'Bogus': 1, 'maxSpawnedZombies': 99},
                                           'pickups': {'nuke': 500}, 'box': {'m_MinWeapons': 12}}})
        for words in ('at once', 'Bogus', 'Power-ups', '"Gone"', 'health x', 'two round sets',
                      '"at least" (9)', 'Zombies alive at most', 'at least more weapons'):
            self.assertTrue(any(words in p for p in problems), (words, problems))

    def test_pickups_store_only_changes(self):
        economy = {'pickups': {'nuke': 0}}
        self.assertEqual(game.pickup_weights(economy), [10, 10, 10, 0, 10, 10, 10, 10, 0])
        self.assertEqual(game.pickup_weights({'pickups': [1] * 9}), [1] * 9)
        self.assertIsNone(game.pickup_weights({}))


class Rest(unittest.TestCase):
    def test_zombie_looks(self):
        level = statics()
        looks = game.read_zombie_types(level)
        self.assertEqual(len(looks['all']), 2)
        game.write_zombie_types(level, [iw_hash('look_b')])
        self.assertEqual(game.read_zombie_types(level)['used'], [iw_hash('look_b')])
        with self.assertRaises(game.GameError):
            game.write_zombie_types(level, [123])

    def test_scores_and_box_and_runtime(self):
        level = statics()
        groups = {'mymap_statics.group.bin': level}
        data = {'economy': {'scores': {'SUBJECT_ZOMBIE_SCORE_HIT': 20}, 'box': {'m_Cost': 1500},
                            'cvars': {'StartingScore': 2000}, 'pickups': [0, 0, 10, 0, 0, 0, 0, 0, 0]},
                'level': {'power_on': True}, 'rounds': None}
        with tempfile.TemporaryDirectory() as temp:
            out = game.apply(data, Path(temp), groups, 'mymap')
        self.assertEqual(out['cvars']['StartingScore'], 2000)
        self.assertEqual(out['cvars']['ScoreConfigName'], 'boz_score_mymap')
        self.assertEqual(out['cvars']['ProbabilityOfSpawningEachPickup'], '{0,0,10,0,0,0,0,0,0}')
        self.assertTrue(out['power_on'])
        table = next(r for t in level.types() if t.class_hash == game.SCORE_CONFIG for r in t.resources)
        blob = resources.decode_reflected(table.body)
        self.assertEqual(len(blob.properties[0].elements), 1)
        costs = {}
        for t in level.types():
            if t.class_hash == resources.ENTITY_SPEC:
                for r in t.resources:
                    spec = resources.decode_entity_spec(r.body)
                    costs[r.in_group_hash] = reflect.typed_value(spec.components[0].blob.properties[0])
        self.assertEqual(costs[iw_hash('box_stock')], 1500)
        self.assertEqual(costs[iw_hash('box_own')], 400)                 # its own cost stays
        group.parse(group.encode(level))

    def test_project_file(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(game.load(Path(temp)), {})
            game.save(Path(temp), {'level': {'power_on': True}})
            self.assertEqual(game.load(Path(temp)), {'level': {'power_on': True}})
            manifest = Path(temp, 'boz-project.toml')
            source = Path(temp, 'source')
            manifest.write_text('schema = 2\n[mod]\n', encoding='utf-8')
            game.save(source, {})
            self.assertIn('schema = 3', manifest.read_text(encoding='utf-8'))

    def test_every_field_documented(self):
        for field in game.FIELDS:
            self.assertTrue(field.label and field.help, field.name)
        for name, (label, unit, help_text, default) in game.CVARS.items():
            self.assertTrue(label and help_text, name)



class Encodings(unittest.TestCase):
    def test_score_table_has_points_and_limits(self):
        blob = resources.decode_reflected(game.score_config({'SUBJECT_ZOMBIE_SCORE_HIT': 20}))
        names = [p.name_hash for p in blob.properties]
        self.assertEqual(names, [iw_hash('m_ScoreLimits'), iw_hash('m_Scores')])
        pair = blob.properties[1].elements[0].properties
        self.assertEqual(pair[0].type_hash, iw_hash('std::string'))     # what the game reads
        shared = group.Group(bytes((0x3D, 0, 0, 0, 0, 0)), [group.Section(group.RESOURCES, b'', [
            group.ResourceType(game.SCORE_CONFIG, 1, 1, [group.Resource(None, iw_hash('score_table'),
                                                                        game.score_config({'X': 5}, {'X': 7}))])])])
        self.assertEqual(game.read_scores(shared), {'X': 5})
        self.assertEqual(game.read_scores(shared, 'm_ScoreLimits'), {'X': 7})

    def test_etc1_round_trip(self):
        from bozkit import native
        width = height = 16
        rgb = b''.join(bytes((x * 15 % 256, y * 15 % 256, 128)) for y in range(height) for x in range(width))
        blocks = native.encode_etc1(rgb, width, height)
        self.assertEqual(len(blocks), (width // 4) * (height // 4) * 8)
        back = native.decode_etc1(blocks, width, height)
        error = sum(abs(back[i * 4 + c] - rgb[i * 3 + c]) for i in range(width * height) for c in range(3))
        self.assertLess(error / (width * height * 3), 12)


if __name__ == '__main__':
    unittest.main()
