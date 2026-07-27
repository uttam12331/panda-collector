"""Panda Collector -- a small third-person 3D game built with Panda3D.

Guide the panda around the field, collect all the glowing orbs before the
timer runs out, and avoid the roaming hazards. The game uses only the models
that ship with Panda3D, so it runs anywhere with ``pip install panda3d`` -- no
external assets required.

Run it with::

    python main.py

Controls:
    Arrow keys / WASD  move and turn the panda
    R                  restart after winning or losing
    Escape             quit
"""

from __future__ import annotations

import random
import sys

from direct.actor.Actor import Actor
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import (
    AmbientLight,
    ClockObject,
    CollisionHandlerEvent,
    CollisionNode,
    CollisionSphere,
    CollisionTraverser,
    DirectionalLight,
    NodePath,
    TextNode,
    Vec3,
    Vec4,
)

# --- Tuning -----------------------------------------------------------------
FIELD_RADIUS = 55.0          # how far from the centre the panda may roam
NUM_ORBS = 8                 # orbs to collect to win
NUM_HAZARDS = 3              # roaming hazards to avoid
TIME_LIMIT = 60.0            # seconds to collect everything
MOVE_SPEED = 18.0            # units / second
TURN_SPEED = 130.0           # degrees / second
HAZARD_SPEED = 6.0           # units / second
PLAYER_RADIUS = 2.0          # collision radius around the panda
ORB_RADIUS = 2.5
HAZARD_RADIUS = 2.5


class CollectorGame(ShowBase):
    """The whole game lives in this ShowBase subclass."""

    def __init__(self) -> None:
        super().__init__()
        self.disableMouse()  # we drive the camera ourselves
        self.setBackgroundColor(0.06, 0.08, 0.12)
        self.clock = ClockObject.getGlobalClock()

        self._build_environment()
        self._build_lighting()
        self._build_player()
        self._build_collision()
        self._build_hud()
        self._bind_input()

        self.orbs: list[NodePath] = []
        self.hazards: list[dict] = []
        self.start_new_game()

        self.taskMgr.add(self._update, "update")

    # -- scene setup ---------------------------------------------------------
    def _build_environment(self) -> None:
        """Load the ground/environment that ships with Panda3D."""
        self.environ = self.loader.loadModel("models/environment")
        self.environ.reparentTo(self.render)
        self.environ.setScale(0.28)
        self.environ.setPos(-8, 42, 0)

    def _build_lighting(self) -> None:
        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.45, 0.45, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(ambient))

        sun = DirectionalLight("sun")
        sun.setColor(Vec4(0.9, 0.85, 0.7, 1))
        sun_np = self.render.attachNewNode(sun)
        sun_np.setHpr(-40, -60, 0)
        self.render.setLight(sun_np)

    def _build_player(self) -> None:
        """The player is the animated panda actor from Panda3D's samples.

        It is parented to an invisible ``player`` node that we move and turn;
        the model itself only supplies the visuals and the walk cycle.
        """
        self.player = self.render.attachNewNode("player")
        self.panda = Actor(
            "models/panda-model", {"walk": "models/panda-walk4"}
        )
        self.panda.reparentTo(self.player)
        self.panda.setScale(0.0045)
        self.panda.setH(180)  # face the same way the player node points (+Y)
        self.walking = False

    def _build_collision(self) -> None:
        """Set up Panda3D's collision system for player-vs-object contacts.

        A sphere around the player is the only "from" collider; orbs and
        hazards are "into" colliders. A pattern-based handler turns contacts
        into ``orb-hit`` / ``hazard-hit`` events.
        """
        self.cTrav = CollisionTraverser("traverser")
        self.handler = CollisionHandlerEvent()
        # "%in" expands to the name of the object collided *into* (orb/hazard),
        # so contacts fire an "orb-hit" or "hazard-hit" event.
        self.handler.addInPattern("%in-hit")

        sphere = CollisionSphere(0, 0, 3, PLAYER_RADIUS)
        node = CollisionNode("player")
        node.addSolid(sphere)
        # the player collides *into* orbs/hazards, so restrict its masks
        node.setFromCollideMask(1)
        node.setIntoCollideMask(0)
        self.player_col = self.player.attachNewNode(node)
        self.cTrav.addCollider(self.player_col, self.handler)

        self.accept("orb-hit", self._on_orb)
        self.accept("hazard-hit", self._on_hazard)

    def _build_hud(self) -> None:
        self.hud_score = self._make_text(-1.3, 0.92, align=TextNode.ALeft)
        self.hud_time = self._make_text(1.3, 0.92, align=TextNode.ARight)
        self.center_text = OnscreenText(
            text="",
            pos=(0, 0.1),
            scale=0.12,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 0.7),
            align=TextNode.ACenter,
            mayChange=True,
        )
        self._make_text(
            0, -0.94, scale=0.05, align=TextNode.ACenter
        ).setText("Arrow keys / WASD to move    R to restart    Esc to quit")

    def _make_text(self, x, y, scale=0.06, align=TextNode.ALeft) -> OnscreenText:
        return OnscreenText(
            text="",
            pos=(x, y),
            scale=scale,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 0.6),
            align=align,
            mayChange=True,
        )

    def _bind_input(self) -> None:
        self.keys = {"left": False, "right": False, "up": False, "down": False}
        bindings = {
            "arrow_left": "left", "a": "left",
            "arrow_right": "right", "d": "right",
            "arrow_up": "up", "w": "up",
            "arrow_down": "down", "s": "down",
        }
        for key, action in bindings.items():
            self.accept(key, self._set_key, [action, True])
            self.accept(f"{key}-up", self._set_key, [action, False])
        self.accept("r", self.start_new_game)
        self.accept("escape", sys.exit)

    def _set_key(self, action: str, value: bool) -> None:
        self.keys[action] = value

    # -- game lifecycle ------------------------------------------------------
    def start_new_game(self) -> None:
        """(Re)initialise a round: reset the panda, orbs, hazards and timer."""
        self._clear_round()

        self.player.setPos(0, 0, 0)
        self.player.setH(0)
        self.score = 0
        self.time_left = TIME_LIMIT
        self.state = "playing"
        self.center_text.setText("")

        self._spawn_orbs()
        self._spawn_hazards()
        self._update_hud()

    def _clear_round(self) -> None:
        for orb in getattr(self, "orbs", []):
            orb.removeNode()
        for hazard in getattr(self, "hazards", []):
            hazard["np"].removeNode()
        self.orbs = []
        self.hazards = []

    def _random_ground_pos(self, min_dist: float = 8.0) -> Vec3:
        """A random point on the field, at least ``min_dist`` from the centre."""
        while True:
            x = random.uniform(-FIELD_RADIUS, FIELD_RADIUS)
            y = random.uniform(-FIELD_RADIUS, FIELD_RADIUS)
            if min_dist <= (x * x + y * y) ** 0.5 <= FIELD_RADIUS:
                return Vec3(x, y, 0)

    def _spawn_orbs(self) -> None:
        for _ in range(NUM_ORBS):
            orb = self.loader.loadModel("models/smiley")
            orb.reparentTo(self.render)
            orb.setScale(1.4)
            orb.setColor(0.3, 1.0, 0.6, 1)
            orb.setPos(self._random_ground_pos() + Vec3(0, 0, 3))
            orb.hprInterval(3.0, Vec3(360, 0, 0)).loop()  # gentle spin

            node = CollisionNode("orb")
            node.addSolid(CollisionSphere(0, 0, 0, ORB_RADIUS))
            node.setIntoCollideMask(1)
            node.setFromCollideMask(0)
            orb.attachNewNode(node)
            self.orbs.append(orb)

    def _spawn_hazards(self) -> None:
        for _ in range(NUM_HAZARDS):
            hazard = self.loader.loadModel("models/frowney")
            hazard.reparentTo(self.render)
            hazard.setScale(1.6)
            hazard.setColor(1.0, 0.35, 0.35, 1)
            hazard.setPos(self._random_ground_pos(min_dist=18) + Vec3(0, 0, 3))

            node = CollisionNode("hazard")
            node.addSolid(CollisionSphere(0, 0, 0, HAZARD_RADIUS))
            node.setIntoCollideMask(1)
            node.setFromCollideMask(0)
            hazard.attachNewNode(node)

            angle = random.uniform(0, 360)
            heading = Vec3(0, 0, 0)
            self.hazards.append(
                {"np": hazard, "dir": angle, "heading": heading}
            )

    # -- per-frame update ----------------------------------------------------
    def _update(self, task: Task.Task) -> int:
        dt = self.clock.getDt()
        if self.state == "playing":
            self._move_player(dt)
            self._move_hazards(dt)
            self._tick_timer(dt)
            self.cTrav.traverse(self.render)
        self._follow_camera()
        return Task.cont

    def _move_player(self, dt: float) -> None:
        if self.keys["left"]:
            self.player.setH(self.player.getH() + TURN_SPEED * dt)
        if self.keys["right"]:
            self.player.setH(self.player.getH() - TURN_SPEED * dt)

        moving = False
        if self.keys["up"]:
            self.player.setY(self.player, MOVE_SPEED * dt)
            moving = True
        elif self.keys["down"]:
            self.player.setY(self.player, -MOVE_SPEED * dt)
            moving = True

        self._clamp_to_field(self.player)
        self._set_walking(moving)

    def _clamp_to_field(self, np: NodePath) -> None:
        pos = np.getPos()
        dist = (pos.x * pos.x + pos.y * pos.y) ** 0.5
        if dist > FIELD_RADIUS:
            scale = FIELD_RADIUS / dist
            np.setPos(pos.x * scale, pos.y * scale, pos.z)

    def _set_walking(self, moving: bool) -> None:
        """Play the walk cycle only while moving -- stop it when idle."""
        if moving and not self.walking:
            self.panda.loop("walk")
            self.walking = True
        elif not moving and self.walking:
            self.panda.stop()
            self.walking = False

    def _move_hazards(self, dt: float) -> None:
        for hazard in self.hazards:
            np = hazard["np"]
            np.setH(hazard["dir"])
            np.setY(np, HAZARD_SPEED * dt)
            pos = np.getPos()
            dist = (pos.x * pos.x + pos.y * pos.y) ** 0.5
            if dist > FIELD_RADIUS:  # bounce back toward the centre
                hazard["dir"] = (hazard["dir"] + 180) % 360
                self._clamp_to_field(np)

    def _tick_timer(self, dt: float) -> None:
        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0
            self._end_game(won=False, message="Out of time!")
        self._update_hud()

    def _follow_camera(self) -> None:
        """Keep the camera behind and above the player, looking at it."""
        behind = self.render.getRelativeVector(self.player, Vec3(0, -1, 0))
        target = self.player.getPos() + behind * 26 + Vec3(0, 0, 15)
        self.camera.setPos(self.camera.getPos() * 0.85 + target * 0.15)
        self.camera.lookAt(self.player.getPos() + Vec3(0, 0, 4))

    # -- collision responses -------------------------------------------------
    def _on_orb(self, entry) -> None:
        if self.state != "playing":
            return
        orb = entry.getIntoNodePath().getParent()
        if orb in self.orbs:
            self.orbs.remove(orb)
            orb.removeNode()
            self.score += 1
            if not self.orbs:
                self._end_game(won=True, message="You collected them all!")
            self._update_hud()

    def _on_hazard(self, entry) -> None:
        if self.state == "playing":
            self._end_game(won=False, message="A hazard got you!")

    def _end_game(self, won: bool, message: str) -> None:
        self.state = "won" if won else "lost"
        if self.walking:
            self.panda.stop()
            self.walking = False
        colour = "You win!" if won else "Game over"
        self.center_text.setText(f"{colour}\n{message}\n\nPress R to play again")

    # -- hud -----------------------------------------------------------------
    def _update_hud(self) -> None:
        self.hud_score.setText(f"Orbs: {self.score} / {NUM_ORBS}")
        self.hud_time.setText(f"Time: {self.time_left:0.0f}s")


if __name__ == "__main__":
    CollectorGame().run()
