// boz-navmesh: build stock Detour v7 tiles for BOZ levels with Recast.
//
// bozkit writes a request file and reads the tiles back; it then re-packs them into BOZ's
// widened dtPoly / dtOffMeshConnection layout and restores the game's polygon tags. This program
// only knows standard Recast/Detour and follows the RecastDemo tiled build (Sample_TileMesh).
//
// Request (little-endian):
//   char[4] "BOZN", u32 version (1, or 2 followed by u32 options: bit 0 skips the low-hanging
//   obstacle filter, bit 1 the ledge filter, bit 2 the low-height filter; bits 3-4 select region
//   partitioning: 0 watershed, 1 monotone, 2 layers)
//   f32 cellSize, cellHeight, agentHeight, agentRadius, agentMaxClimb, agentMaxSlope
//   i32 regionMinSize, regionMergeSize; f32 edgeMaxLen, edgeMaxError; i32 vertsPerPoly
//   f32 detailSampleDist, detailSampleMaxError; f32 tileWidth; f32 origin[3]; f32 bmin[3], bmax[3]
//   u32 vertexCount, f32 vertices[3 * vertexCount]      (metres, Y up)
//   u32 triangleCount, i32 triangles[3 * triangleCount]
//   u32 tileCount, i32 tiles[2 * tileCount]              (tile x, tile y)
//   u32 linkCount, per link: f32 start[3], f32 end[3], f32 radius, u8 bidirectional, u32 userId
// Reply:
//   char[4] "BOZT", u32 tileCount, per tile: i32 x, i32 y, u32 size, u8 data[size]
//   (tiles without walkable polygons are left out)

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "DetourNavMeshBuilder.h"
#include "Recast.h"

namespace {

struct Link {
	float start[3], end[3], radius;
	unsigned char bidirectional;
	unsigned int userId;
};

struct Request {
	float cs, ch, agentHeight, agentRadius, agentClimb, agentSlope;
	int regionMinSize, regionMergeSize;
	float edgeMaxLen, edgeMaxError;
	int vertsPerPoly;
	float detailSampleDist, detailSampleMaxError, tileWidth;
	float origin[3], bmin[3], bmax[3];
	uint32_t options = 0;
	std::vector<float> verts;
	std::vector<int> tris;
	std::vector<int> tiles;
	std::vector<Link> links;
};

struct Reader {
	FILE* file;
	bool ok = true;
	template <typename T> T get() {
		T value{};
		if (std::fread(&value, sizeof(T), 1, file) != 1) ok = false;
		return value;
	}
	template <typename T> void get(T* values, size_t count) {
		if (count && std::fread(values, sizeof(T), count, file) != count) ok = false;
	}
};

bool readRequest(const char* path, Request& r) {
	FILE* file = std::fopen(path, "rb");
	if (!file) return false;
	Reader in{file};
	char magic[4];
	in.get(magic, 4);
	uint32_t version = in.get<uint32_t>();
	if (std::memcmp(magic, "BOZN", 4) != 0 || (version != 1 && version != 2)) {
		std::fclose(file);
		return false;
	}
	if (version == 2) r.options = in.get<uint32_t>();
	r.cs = in.get<float>(); r.ch = in.get<float>();
	r.agentHeight = in.get<float>(); r.agentRadius = in.get<float>();
	r.agentClimb = in.get<float>(); r.agentSlope = in.get<float>();
	r.regionMinSize = in.get<int32_t>(); r.regionMergeSize = in.get<int32_t>();
	r.edgeMaxLen = in.get<float>(); r.edgeMaxError = in.get<float>();
	r.vertsPerPoly = in.get<int32_t>();
	r.detailSampleDist = in.get<float>(); r.detailSampleMaxError = in.get<float>();
	r.tileWidth = in.get<float>();
	in.get(r.origin, 3); in.get(r.bmin, 3); in.get(r.bmax, 3);
	r.verts.resize(in.get<uint32_t>() * 3); in.get(r.verts.data(), r.verts.size());
	r.tris.resize(in.get<uint32_t>() * 3); in.get(r.tris.data(), r.tris.size());
	r.tiles.resize(in.get<uint32_t>() * 2); in.get(r.tiles.data(), r.tiles.size());
	r.links.resize(in.get<uint32_t>());
	for (Link& link : r.links) {
		in.get(link.start, 3); in.get(link.end, 3);
		link.radius = in.get<float>();
		link.bidirectional = in.get<uint8_t>();
		link.userId = in.get<uint32_t>();
	}
	std::fclose(file);
	return in.ok;
}

// Recast build of one tile; returns Detour tile data (dtAlloc'd) or nullptr when empty.
unsigned char* buildTile(const Request& r, int tx, int ty, const std::vector<int>& tileTris,
                         int& dataSize) {
	rcContext ctx(false);
	rcConfig cfg{};
	cfg.cs = r.cs;
	cfg.ch = r.ch;
	cfg.walkableSlopeAngle = r.agentSlope;
	cfg.walkableHeight = (int)std::ceil(r.agentHeight / cfg.ch);
	cfg.walkableClimb = (int)std::floor(r.agentClimb / cfg.ch);
	cfg.walkableRadius = (int)std::ceil(r.agentRadius / cfg.cs);
	cfg.maxEdgeLen = (int)(r.edgeMaxLen / r.cs);
	cfg.maxSimplificationError = r.edgeMaxError;
	cfg.minRegionArea = r.regionMinSize * r.regionMinSize;
	cfg.mergeRegionArea = r.regionMergeSize * r.regionMergeSize;
	cfg.maxVertsPerPoly = r.vertsPerPoly;
	cfg.tileSize = (int)std::lround(r.tileWidth / r.cs);
	cfg.borderSize = cfg.walkableRadius + 3;
	cfg.width = cfg.tileSize + cfg.borderSize * 2;
	cfg.height = cfg.tileSize + cfg.borderSize * 2;
	cfg.detailSampleDist = r.detailSampleDist < 0.9f ? 0 : r.cs * r.detailSampleDist;
	cfg.detailSampleMaxError = r.ch * r.detailSampleMaxError;

	float tileBmin[3] = {r.origin[0] + tx * r.tileWidth, r.bmin[1], r.origin[2] + ty * r.tileWidth};
	float tileBmax[3] = {tileBmin[0] + r.tileWidth, r.bmax[1], tileBmin[2] + r.tileWidth};
	rcVcopy(cfg.bmin, tileBmin);
	rcVcopy(cfg.bmax, tileBmax);
	cfg.bmin[0] -= cfg.borderSize * cfg.cs;
	cfg.bmin[2] -= cfg.borderSize * cfg.cs;
	cfg.bmax[0] += cfg.borderSize * cfg.cs;
	cfg.bmax[2] += cfg.borderSize * cfg.cs;

	if (tileTris.empty()) return nullptr;
	rcHeightfield* solid = rcAllocHeightfield();
	if (!solid || !rcCreateHeightfield(&ctx, *solid, cfg.width, cfg.height, cfg.bmin, cfg.bmax,
	                                   cfg.cs, cfg.ch)) {
		rcFreeHeightField(solid);
		return nullptr;
	}
	std::vector<unsigned char> areas(tileTris.size() / 3, 0);
	rcMarkWalkableTriangles(&ctx, cfg.walkableSlopeAngle, r.verts.data(), (int)r.verts.size() / 3,
	                        tileTris.data(), (int)tileTris.size() / 3, areas.data());
	rcRasterizeTriangles(&ctx, r.verts.data(), (int)r.verts.size() / 3, tileTris.data(),
	                     areas.data(), (int)tileTris.size() / 3, *solid, cfg.walkableClimb);
	if (!(r.options & 1)) rcFilterLowHangingWalkableObstacles(&ctx, cfg.walkableClimb, *solid);
	if (!(r.options & 2)) rcFilterLedgeSpans(&ctx, cfg.walkableHeight, cfg.walkableClimb, *solid);
	if (!(r.options & 4)) rcFilterWalkableLowHeightSpans(&ctx, cfg.walkableHeight, *solid);

	rcCompactHeightfield* chf = rcAllocCompactHeightfield();
	bool built = chf && rcBuildCompactHeightfield(&ctx, cfg.walkableHeight, cfg.walkableClimb,
	                                              *solid, *chf);
	rcFreeHeightField(solid);
	built = built && rcErodeWalkableArea(&ctx, cfg.walkableRadius, *chf);
	const unsigned partition = (r.options >> 3) & 3;
	if (partition == 1) {
		built = built && rcBuildRegionsMonotone(&ctx, *chf, cfg.borderSize, cfg.minRegionArea,
		                                        cfg.mergeRegionArea);
	} else if (partition == 2) {
		built = built && rcBuildLayerRegions(&ctx, *chf, cfg.borderSize, cfg.minRegionArea);
	} else {
		built = built && rcBuildDistanceField(&ctx, *chf);
		built = built && rcBuildRegions(&ctx, *chf, cfg.borderSize, cfg.minRegionArea,
		                                cfg.mergeRegionArea);
	}
	rcContourSet* cset = built ? rcAllocContourSet() : nullptr;
	built = cset && rcBuildContours(&ctx, *chf, cfg.maxSimplificationError, cfg.maxEdgeLen, *cset);
	built = built && cset->nconts > 0;
	rcPolyMesh* pmesh = built ? rcAllocPolyMesh() : nullptr;
	built = pmesh && rcBuildPolyMesh(&ctx, *cset, cfg.maxVertsPerPoly, *pmesh);
	rcPolyMeshDetail* dmesh = built ? rcAllocPolyMeshDetail() : nullptr;
	built = dmesh && rcBuildPolyMeshDetail(&ctx, *pmesh, *chf, cfg.detailSampleDist,
	                                       cfg.detailSampleMaxError, *dmesh);
	rcFreeCompactHeightfield(chf);
	rcFreeContourSet(cset);
	unsigned char* data = nullptr;
	if (built && pmesh->npolys > 0) {
		std::vector<unsigned short> flags(pmesh->npolys, 0);
		for (int i = 0; i < pmesh->npolys; ++i) {
			flags[i] = pmesh->areas[i] == RC_WALKABLE_AREA ? 1 : 0;
			pmesh->areas[i] = 0;  // BOZ keeps area 0; bozkit restores the game's flags
		}
		// Off-mesh links start in the tile that contains their start point.
		std::vector<float> linkVerts, linkRad;
		std::vector<unsigned short> linkFlags;
		std::vector<unsigned char> linkAreas, linkDir;
		std::vector<unsigned int> linkIds;
		for (const Link& link : r.links) {
			if (link.start[0] < tileBmin[0] || link.start[0] >= tileBmax[0] ||
			    link.start[2] < tileBmin[2] || link.start[2] >= tileBmax[2])
				continue;
			linkVerts.insert(linkVerts.end(), link.start, link.start + 3);
			linkVerts.insert(linkVerts.end(), link.end, link.end + 3);
			linkRad.push_back(link.radius);
			linkFlags.push_back(1);
			linkAreas.push_back(0);
			linkDir.push_back(link.bidirectional ? 1 : 0);
			linkIds.push_back(link.userId);
		}
		dtNavMeshCreateParams params{};
		params.verts = pmesh->verts;
		params.vertCount = pmesh->nverts;
		params.polys = pmesh->polys;
		params.polyAreas = pmesh->areas;
		params.polyFlags = flags.data();
		params.polyCount = pmesh->npolys;
		params.nvp = pmesh->nvp;
		params.detailMeshes = dmesh->meshes;
		params.detailVerts = dmesh->verts;
		params.detailVertsCount = dmesh->nverts;
		params.detailTris = dmesh->tris;
		params.detailTriCount = dmesh->ntris;
		params.offMeshConVerts = linkVerts.data();
		params.offMeshConRad = linkRad.data();
		params.offMeshConFlags = linkFlags.data();
		params.offMeshConAreas = linkAreas.data();
		params.offMeshConDir = linkDir.data();
		params.offMeshConUserID = linkIds.data();
		params.offMeshConCount = (int)linkIds.size();
		params.walkableHeight = r.agentHeight;
		params.walkableRadius = r.agentRadius;
		params.walkableClimb = r.agentClimb;
		params.tileX = tx;
		params.tileY = ty;
		params.tileLayer = 0;
		rcVcopy(params.bmin, pmesh->bmin);
		rcVcopy(params.bmax, pmesh->bmax);
		params.cs = cfg.cs;
		params.ch = cfg.ch;
		params.buildBvTree = true;
		if (!dtCreateNavMeshData(&params, &data, &dataSize)) data = nullptr;
	}
	rcFreePolyMesh(pmesh);
	rcFreePolyMeshDetail(dmesh);
	return data;
}

}  // namespace

int main(int argc, char** argv) {
	if (argc != 3) {
		std::fprintf(stderr, "usage: boz-navmesh request.bin tiles.bin\n");
		return 2;
	}
	Request r;
	if (!readRequest(argv[1], r)) {
		std::fprintf(stderr, "boz-navmesh: cannot read request %s\n", argv[1]);
		return 1;
	}
	FILE* out = std::fopen(argv[2], "wb");
	if (!out) {
		std::fprintf(stderr, "boz-navmesh: cannot write %s\n", argv[2]);
		return 1;
	}
	std::fwrite("BOZT", 1, 4, out);
	uint32_t written = 0;
	long countPos = std::ftell(out);
	std::fwrite(&written, 4, 1, out);
	const float pad = r.agentRadius + r.cs * 4;
	for (size_t t = 0; t < r.tiles.size(); t += 2) {
		int tx = r.tiles[t], ty = r.tiles[t + 1];
		float minX = r.origin[0] + tx * r.tileWidth - pad, maxX = minX + r.tileWidth + 2 * pad;
		float minZ = r.origin[2] + ty * r.tileWidth - pad, maxZ = minZ + r.tileWidth + 2 * pad;
		std::vector<int> tileTris;
		for (size_t i = 0; i < r.tris.size(); i += 3) {
			float lo[2] = {1e30f, 1e30f}, hi[2] = {-1e30f, -1e30f};
			for (int k = 0; k < 3; ++k) {
				const float* v = &r.verts[r.tris[i + k] * 3];
				lo[0] = std::fmin(lo[0], v[0]); hi[0] = std::fmax(hi[0], v[0]);
				lo[1] = std::fmin(lo[1], v[2]); hi[1] = std::fmax(hi[1], v[2]);
			}
			if (hi[0] >= minX && lo[0] <= maxX && hi[1] >= minZ && lo[1] <= maxZ)
				tileTris.insert(tileTris.end(), &r.tris[i], &r.tris[i] + 3);
		}
		int size = 0;
		unsigned char* data = buildTile(r, tx, ty, tileTris, size);
		if (!data) continue;
		int32_t header[2] = {tx, ty};
		uint32_t usize = (uint32_t)size;
		std::fwrite(header, 4, 2, out);
		std::fwrite(&usize, 4, 1, out);
		std::fwrite(data, 1, size, out);
		dtFree(data);
		++written;
	}
	std::fseek(out, countPos, SEEK_SET);
	std::fwrite(&written, 4, 1, out);
	std::fclose(out);
	return 0;
}
