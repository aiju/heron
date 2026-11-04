"""A real-time strategy game's logic, headless.

It stands for the games on Heron Mini, and follows its RTS
(studies/mini_gfx/games/rts on the trusting-fermi branch: map.c, units.c
and render.c's bookkeeping) without the drawing, which the sprite
workloads cover: a 96 x 64 tile map made from a seed (grass, a river with
two fords, lakes, forests, rocks, two halls), 200 units in two teams
(soldiers, archers, and workers walking between their hall and the
forest), and a script of orders to groups. An order builds a flow field
by a breadth-first search from its target, spread over ticks (256 cells
a tick for all fields together); its units take places in a spiral
formation round the target and walk down the field, planning only at
waypoints. Every tick each unit steps on an occupancy grid (one unit to
an 8-pixel cell, side-stepping 45 and 90 degrees round others), every
eighth looks for the nearest enemy through 64-pixel buckets, and fights:
melee blows, arrows in flight, the fallen. Then the frame's bookkeeping:
the units sorted by y, the drawing list of those in the 640 x 400
viewport with their sprites, the dirty tiles where units moved or fell
and the units that touch them, and every fourth tick the minimap.
Positions are fixed point (pixels x 16); the random numbers are the
game's own LCG. The results: hashes of the units' state every REPORT
ticks, of every minimap and every frame's drawing list, and counts.

The sizes: `test` a 32 x 16 map, 16 units, 3 ticks; `small` the 96 x 64
map, 200 units, 6 ticks (about 0.4 s of game time at 1.4 M
instructions: the game costs some 150,000 instructions a tick with 200
units, close to the Mini game's own measured cost per unit); `ref` the
same for 60 ticks, about 4 s of game time.

Where the time goes (`small`; at `ref` start-up is a twentieth): a
quarter in start-up, making the map (12%,
four passes over its 6,144 cells) and placing the units; the rest in the
ticks: the frame's bookkeeping (view_frame, sort_units, cell_dirty,
touches_dirty, the minimap: about 30%), steering on the occupancy grid
(try_step, unit_steer: 11%), the nearest-enemy searches (10%), clearing
new flow fields (memset, 8%) and searching them (field_step, 4%),
planning, the buckets and combat. No one loop dominates.
"""

TITLE = "a real-time strategy game's logic: flow fields, steering, combat"
PART = "c"
CATEGORY = "games"
SOURCES = ["game.c", "map.c", "units.c", "combat.c", "view.c"]
SIZES = {
    "test": {"MAP_W": 32, "MAP_H": 16, "NUNITS": 16, "TICKS": 3, "REPORT": 1},
    "small": {"MAP_W": 96, "MAP_H": 64, "NUNITS": 200, "TICKS": 6, "REPORT": 2},
    "ref": {"MAP_W": 96, "MAP_H": 64, "NUNITS": 200, "TICKS": 60, "REPORT": 2}
}
