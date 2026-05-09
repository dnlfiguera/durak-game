"""
game_server.py
==============
FastAPI + WebSocket server for online Durak.

- Two players connect via WebSocket
- Server holds the GameState and enforces all rules
- Each player only receives their own hand + public info
- Messages are JSON

Run locally:
    pip install fastapi uvicorn
    uvicorn game_server:app --host 0.0.0.0 --port 8000 --reload

Then open in browser:
    http://localhost:8000          <- Player 1 (same PC)
    http://<your-local-ip>:8000   <- Player 2 (other device, same WiFi)

Find your local IP:
    Windows: ipconfig  (look for IPv4 Address, e.g. 192.168.1.42)
    Mac/Linux: ifconfig or ip a
"""

from __future__ import annotations
import asyncio
import json
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from game_engine import GameState, GamePhase, Card, RANK_NAMES

app = FastAPI()

# ---------------------------------------------------------------------------
# Room manager — handles one game room with 2 players
# ---------------------------------------------------------------------------

class PlayerConnection:
    def __init__(self, ws: WebSocket, name: str, index: int):
        self.ws = ws
        self.name = name
        self.index = index          # 0 or 1 in gs.players
        self.connected = True

    async def send(self, msg: dict):
        if not self.connected:
            return
        try:
            await self.ws.send_text(json.dumps(msg))
        except Exception as e:
            print(f"[Send Error] {self.name}: {e}")
            self.connected = False


class GameRoom:
    def __init__(self, room_id: str, max_players: int = 4):
        self.room_id = room_id
        self.max_players = max_players
        self.players: list[PlayerConnection] = []
        self.gs: Optional[GameState] = None
        self.started = False

    def is_full(self) -> bool:
        return len(self.players) >= self.max_players

    def has_slot_for(self, name: str) -> bool:
        """Check if a player with this name can reconnect."""
        for p in self.players:
            if p.name == name and not p.connected:
                return True
        return not self.is_full()

    def add_player(self, ws: WebSocket, name: str) -> PlayerConnection:
        index = len(self.players)
        pc = PlayerConnection(ws, name, index)
        self.players.append(pc)
        return pc

    def reconnect_player(self, ws: WebSocket, name: str) -> Optional[PlayerConnection]:
        """Reconnect a disconnected player by name."""
        for p in self.players:
            if p.name == name and not p.connected:
                p.ws = ws
                p.connected = True
                return p
        return None

    def start_game(self):
        names = [p.name for p in self.players]
        self.gs = GameState(names)
        self.started = True

    def get_player_by_ws(self, ws: WebSocket) -> Optional[PlayerConnection]:
        for p in self.players:
            if p.ws == ws:
                return p
        return None

    def all_connected(self) -> bool:
        return all(p.connected for p in self.players)

    async def broadcast_lobby(self):
        """Send lobby state to all connected players."""
        player_names = [p.name for p in self.players]
        count = len(self.players)
        print(f"[Lobby] Broadcasting to {count} players: {player_names}")
        for p in self.players:
            print(f"[Lobby] Sending to {p.name} (connected={p.connected})")
            await p.send({
                "type": "lobby_update",
                "players": player_names,
                "count": count,
                "max": self.max_players,
                "is_host": p.index == 0,
                "message": f"{count}/{self.max_players} players joined: {', '.join(player_names)}"
            })

    # ------------------------------------------------------------------
    # State snapshots sent to each player
    # ------------------------------------------------------------------

    def _public_state(self) -> dict:
        """Info visible to all players."""
        gs = self.gs
        return {
            "trump": gs.trump,
            "trump_card": str(gs.deck.trump_card),
            "deck_size": len(gs.deck),
            "discard_size": len(gs.discard),
            "phase": gs.phase.value,
            "attacker": gs.attacker.name,
            "defender": gs.defender.name,
            "table": {
                "attacks": [str(c) for c in gs.table.attacks],
                "defenses": {str(k): str(v) for k, v in gs.table.defenses.items()},
            },
            "all_players": [p.name for p in gs.players],
            "hand_sizes": {p.name: len(p.hand) for p in gs.players},
            "winners": [p.name for p in gs.winners],
            "durak": gs.durak.name if gs.durak else None,
            "can_transfer": gs.can_transfer(),
            "transfer_target": gs.players[gs._transfer_target_index()].name
                               if gs.can_transfer() else None,
            "num_players": len(gs.players),
        }

    def state_for(self, pc: PlayerConnection) -> dict:
        """Full state snapshot for one player (includes their hand)."""
        gs = self.gs
        player = gs.players[pc.index]
        pub = self._public_state()
        pub["your_name"] = player.name
        pub["your_hand"] = [str(c) for c in player.hand]
        pub["your_index"] = pc.index
        pub["is_attacker"] = (player == gs.attacker)
        pub["is_defender"] = (player == gs.defender)
        pub["valid_attacks"] = self._valid_attacks(player)
        pub["valid_defenses"] = self._valid_defenses(player)
        pub["valid_transfers"] = self._valid_transfers(player)
        return pub

    def _valid_attacks(self, player) -> list[str]:
        gs = self.gs
        if gs.phase not in (GamePhase.ATTACKING, GamePhase.PILE_ON):
            return []
        if player == gs.defender:
            return []
        if gs.phase == GamePhase.ATTACKING and player != gs.attacker and gs.table.is_empty():
            return []  # only main attacker can start
        if gs.table.is_empty():
            return [str(c) for c in player.hand]
        return [str(c) for c in player.hand
                if c.rank in gs.table.valid_pile_on_ranks()
                and len(gs.table.undefended()) < len(gs.defender.hand)]

    def _valid_defenses(self, player) -> dict:
        """Returns {attack_card_str: [defense_card_str, ...]}"""
        gs = self.gs
        if gs.phase != GamePhase.DEFENDING or player != gs.defender:
            return {}
        result = {}
        for atk in gs.table.undefended():
            valid = [str(c) for c in player.hand if c.beats(atk, gs.trump)]
            if valid:
                result[str(atk)] = valid
        return result

    def _valid_transfers(self, player) -> list[str]:
        gs = self.gs
        if gs.phase != GamePhase.DEFENDING or player != gs.defender:
            return []
        if not gs.can_transfer():
            return []
        attack_ranks = {c.rank for c in gs.table.attacks}
        return [str(c) for c in player.hand if c.rank in attack_ranks]

    # ------------------------------------------------------------------
    # Broadcast updated state to all players
    # ------------------------------------------------------------------

    async def broadcast_state(self, log_msg: str = ""):
        for pc in self.players:
            state = self.state_for(pc)
            state["type"] = "state"
            state["log"] = log_msg
            await pc.send(state)

    async def broadcast(self, msg: dict):
        for pc in self.players:
            await pc.send(msg)

    # ------------------------------------------------------------------
    # Action handler — called when a player sends an action
    # ------------------------------------------------------------------

    async def handle_action(self, pc: PlayerConnection, data: dict):
        gs = self.gs
        action = data.get("action")
        player = gs.players[pc.index]

        result = {"ok": False, "error": "Unknown action"}

        if action == "attack":
            card = self._parse_card(data.get("card"), player)
            if card is None:
                result = {"ok": False, "error": "Card not found in hand"}
            else:
                result = gs.attack(player, card)

        elif action == "defend":
            atk_card = self._parse_card_str(data.get("attack_card"))
            def_card = self._parse_card(data.get("defense_card"), player)
            if atk_card is None or def_card is None:
                result = {"ok": False, "error": "Invalid cards"}
            else:
                result = gs.defend(player, atk_card, def_card)

        elif action == "pickup":
            result = gs.defender_picks_up(player)

        elif action == "end_attack":
            result = gs.end_attack(player)

        elif action == "transfer":
            raw_cards = data.get("cards", [])
            cards = [self._parse_card(c, player) for c in raw_cards]
            if any(c is None for c in cards):
                result = {"ok": False, "error": "One or more cards not found in hand"}
            else:
                result = gs.transfer(player, cards)

        if not result["ok"]:
            # Send error only to the player who made the mistake
            await pc.send({"type": "error", "message": result["error"]})
        else:
            # Broadcast updated state to everyone
            log = gs.log[-1] if gs.log else ""
            await self.broadcast_state(log)

    def _parse_card(self, card_str: str, player) -> Optional[Card]:
        """Find a card in a player's hand by string representation."""
        if not card_str:
            return None
        for c in player.hand:
            if str(c) == card_str:
                return c
        return None

    def _parse_card_str(self, card_str: str) -> Optional[Card]:
        """Find a card anywhere on the table by string."""
        if not card_str:
            return None
        for c in self.gs.table.attacks:
            if str(c) == card_str:
                return c
        return None


# ---------------------------------------------------------------------------
# Room registry — for now just one room ("lobby")
# ---------------------------------------------------------------------------

rooms: dict[str, GameRoom] = {}

def get_or_create_room(room_id: str) -> GameRoom:
    if room_id not in rooms:
        rooms[room_id] = GameRoom(room_id)
    return rooms[room_id]


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    room = get_or_create_room(room_id)

    # Wait for player to send their name
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        data = json.loads(raw)
        name = data.get("name", f"Player {len(room.players)+1}")
    except (asyncio.TimeoutError, json.JSONDecodeError):
        name = f"Player {len(room.players)+1}"

    # --- Try reconnect first ---
    pc = room.reconnect_player(websocket, name)
    if pc:
        # Reconnected! Send current state
        await pc.send({"type": "reconnected", "player_index": pc.index,
                       "your_name": name, "room_id": room_id})
        if room.started and room.gs:
            await pc.send({"type": "start",
                           "message": f"{name} reconnected!"})
            state = room.state_for(pc)
            state["type"] = "state"
            state["log"] = f"{name} reconnected!"
            await pc.send(state)
            # Notify others
            for other in room.players:
                if other != pc and other.connected:
                    await other.send({"type": "opponent_reconnected",
                                      "message": f"{name} reconnected!"})
    else:
        # --- New player ---
        if room.is_full() or room.started:
            await websocket.send_text(json.dumps({
                "type": "error", "message": "Room is full or game already started."
            }))
            await websocket.close()
            return

        pc = room.add_player(websocket, name)
        await pc.send({"type": "joined", "player_index": pc.index,
                       "your_name": name, "room_id": room_id})

        # Small delay to let mobile WebSockets settle
        await asyncio.sleep(0.3)

        # Notify everyone about the lobby
        await room.broadcast_lobby()

    # --- Heartbeat task (keeps connection alive) ---
    async def heartbeat():
        try:
            while pc.connected:
                await asyncio.sleep(25)
                if pc.connected:
                    await pc.send({"type": "ping"})
        except Exception:
            pass

    beat_task = asyncio.create_task(heartbeat())

    # --- Game loop ---
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            # Handle pong from client
            if data.get("type") == "pong":
                # If game hasn't started, re-send lobby state (fixes mobile timing)
                if not room.started and len(room.players) > 1:
                    await room.broadcast_lobby()
                continue

            # Host can start the game when 2+ players are in
            if data.get("action") == "start_game":
                if pc.index != 0:
                    await pc.send({"type": "error", "message": "Only the host can start the game."})
                elif room.started:
                    await pc.send({"type": "error", "message": "Game already started."})
                elif len(room.players) < 2:
                    await pc.send({"type": "error", "message": "Need at least 2 players."})
                else:
                    room.start_game()
                    await room.broadcast({"type": "start",
                                           "message": f"Game starting with {len(room.players)} players!"})
                    await room.broadcast_state("Game started!")
                continue

            if not room.started:
                await pc.send({"type": "error",
                               "message": "Game hasn't started yet. Waiting for host to start."})
                continue

            if room.gs.phase == GamePhase.GAME_OVER:
                await pc.send({"type": "error",
                               "message": "Game is already over."})
                continue

            await room.handle_action(pc, data)

    except WebSocketDisconnect:
        pc.connected = False
        beat_task.cancel()
        # Don't delete the room — allow reconnection
        await room.broadcast({
            "type": "opponent_disconnected",
            "message": f"{pc.name} disconnected. They can rejoin with the same name."
        })


# ---------------------------------------------------------------------------
# HTTP: serve the game client
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Redirect to a default room."""
    return HTMLResponse("""
    <html><head><title>Durak</title></head>
    <body style="background:#1a3a1a;color:#fff;font-family:Arial;text-align:center;padding:60px">
        <h1>Durak Card Game</h1>
        <p>Share a room name with your opponent and both open the link:</p>
        <form onsubmit="go(event)">
            <input id="room" placeholder="Room name (e.g. mygame)" 
                   style="padding:10px;font-size:18px;width:250px">
            <button style="padding:10px 20px;font-size:18px;margin-left:10px">Join</button>
        </form>
        <script>
        function go(e) {
            e.preventDefault();
            const room = document.getElementById('room').value.trim() || 'lobby';
            window.location.href = '/game/' + room;
        }
        </script>
    </body></html>
    """)

@app.get("/game/{room_id}")
async def game_page(room_id: str):
    """Serve the game client for a specific room."""
    import os
    # Look for index.html next to game_server.py
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base_dir, "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html not found — make sure it is in the same folder as game_server.py</h1>", status_code=500)
    return HTMLResponse(html.replace("__ROOM_ID__", room_id))


# ---------------------------------------------------------------------------
# Dev helper: print local IP on startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"
    print("\n" + "="*52)
    print(f"  Durak server running!")
    print(f"")
    print(f"  Your link (this PC):")
    print(f"  http://localhost:8000/game/durak")
    print(f"")
    print(f"  Opponent link (same WiFi):")
    print(f"  http://{local_ip}:8000/game/durak")
    print(f"")
    print(f"  Both open the same link, enter names, and play!")
    print("="*52 + "\n")


# ---------------------------------------------------------------------------
# Run directly with: python game_server.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("game_server:app", host="0.0.0.0", port=port, reload=False)
