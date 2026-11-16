"""Reserved boundary for E1 mapping.

No map is generated in E0. E1 implementation must export final optimized
camera poses, metric PLY, and floor-aligned ray-observed occupancy with
occupied/free/unknown values; absence of points is never evidence of free space.
Store T_floor_map, height bounds, grid origin, axis convention and resolution.
"""
