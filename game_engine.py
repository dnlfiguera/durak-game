"""
game_engine.py
==============
Pure Python Durak game engine.
No graphics, no networking — just the rules.
Can be reused by Pygame, FastAPI/WebSocket, or any front-end.

Durak rules implemented:
  - 36-card deck (6 through Ace, 4 suits)
  - Trump suit determined by bottom card of deck
  - 6 cards dealt to each player at game start
  - Attacker plays a card; defender must beat it with same suit + higher rank, or a trump
  - Other players can "pile on" cards of matching rank (up to defender's hand size)
  - Defender either beats all cards (table cleared) or picks them all up
  - Players refill to 6 cards after each round (attacker first, then others, defender last)
  - Player with no cards when deck is empty is out (wins)
  - Last player holding cards = the Durak (loser)
"""

from __future__ import annotations
import random
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = [6, 7, 8, 9, 10, 11, 12, 13, 14]  # 11=J, 12=Q, 13=K, 14=A
RANK_NAMES = {6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
              11: "J", 12: "Q", 13: "K", 14: "A"}
HAND_SIZE = 6


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card:
    def __init__(self, suit: str, rank: int):
        self.suit = suit
        self.rank = rank

    @property
    def rank_name(self) -> str:
        return RANK_NAMES[self.rank]

    def __repr__(self) -> str:
        return f"{self.rank_name}{self.suit}"

    def __eq__(self, other) -> bool:
        return isinstance(other, Card) and self.suit == other.suit and self.rank == other.rank

    def __hash__(self) -> int:
        return hash((self.suit, self.rank))

    def beats(self, other: "Card", trump: str) -> bool:
        """Return True if this card can defend against `other`."""
        if self.suit == other.suit:
            return self.rank > other.rank
        if self.suit == trump and other.suit != trump:
            return True
        return False


# ---------------------------------------------------------------------------
# Deck
# ---------------------------------------------------------------------------

class Deck:
    def __init__(self):
        self.cards: list[Card] = [Card(s, r) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)
        # Bottom card determines trump suit; place it face-up at the bottom
        self.trump_card: Card = self.cards[0]
        self.trump_suit: str = self.trump_card.suit

    def draw(self) -> Optional[Card]:
        """Draw the top card (end of list). Returns None if empty."""
        return self.cards.pop() if self.cards else None

    def __len__(self) -> int:
        return len(self.cards)

    def __repr__(self) -> str:
        return f"Deck({len(self.cards)} cards, trump={self.trump_suit})"


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, name: str, is_human: bool = True):
        self.name = name
        self.is_human = is_human
        self.hand: list[Card] = []

    def draw_up_to(self, deck: Deck, target: int = HAND_SIZE):
        """Draw cards from deck until hand has `target` cards (or deck runs out)."""
        while len(self.hand) < target and len(deck) > 0:
            card = deck.draw()
            if card:
                self.hand.append(card)

    def has_card(self, card: Card) -> bool:
        return card in self.hand

    def remove_card(self, card: Card):
        self.hand.remove(card)

    def add_cards(self, cards: list[Card]):
        self.hand.extend(cards)

    def lowest_trump(self, trump: str) -> Optional[Card]:
        trumps = [c for c in self.hand if c.suit == trump]
        return min(trumps, key=lambda c: c.rank) if trumps else None

    def is_out(self) -> bool:
        return len(self.hand) == 0

    def __repr__(self) -> str:
        return f"Player({self.name}, {len(self.hand)} cards: {self.hand})"


# ---------------------------------------------------------------------------
# Table (cards played in the current round)
# ---------------------------------------------------------------------------

class Table:
    """
    Tracks attack/defense pairs in the current round.
    attacks  = list of attack cards in order played
    defenses = dict {attack_card: defense_card}
    """
    def __init__(self):
        self.attacks: list[Card] = []
        self.defenses: dict[Card, Card] = {}

    def add_attack(self, card: Card):
        self.attacks.append(card)

    def add_defense(self, attack_card: Card, defense_card: Card):
        self.defenses[attack_card] = defense_card

    def undefended(self) -> list[Card]:
        return [c for c in self.attacks if c not in self.defenses]

    def all_defended(self) -> bool:
        return len(self.undefended()) == 0

    def all_cards(self) -> list[Card]:
        cards = list(self.attacks)
        cards.extend(self.defenses.values())
        return cards

    def valid_pile_on_ranks(self) -> set[int]:
        """Ranks that are already on the table (attackers can pile on matching ranks)."""
        return {c.rank for c in self.all_cards()}

    def is_empty(self) -> bool:
        return len(self.attacks) == 0

    def clear(self):
        self.attacks.clear()
        self.defenses.clear()

    def __repr__(self) -> str:
        pairs = []
        for atk in self.attacks:
            dfn = self.defenses.get(atk, "?")
            pairs.append(f"{atk}→{dfn}")
        return "Table[" + ", ".join(pairs) + "]"


# ---------------------------------------------------------------------------
# GamePhase
# ---------------------------------------------------------------------------

class GamePhase(Enum):
    ATTACKING    = "attacking"    # attacker's turn to play a card
    DEFENDING    = "defending"    # defender must respond
    PILE_ON      = "pile_on"      # attackers may add more cards
    TRANSFERRING = "transferring" # defender redirects attack to next player (Perevod)
    REFILL       = "refill"       # refill hands from deck
    ROUND_OVER   = "round_over"   # round resolved, rotate roles
    GAME_OVER    = "game_over"    # one player left = Durak


# ---------------------------------------------------------------------------
# GameState  (the main engine)
# ---------------------------------------------------------------------------

class GameState:
    """
    Central game engine. Holds all state and enforces the rules.

    Typical call sequence per round:
        attack(attacker, card)          # attacker plays first card
        defend(defender, atk, dfn)      # defender responds
        pile_on(player, card)           # optional extra attacks
        defend(...)                     # defender responds to pile-ons
        end_attack()                    # attacker passes / no more pile-ons
          → if all defended: table cleared, defender becomes next attacker
          → if not defended: defender picks up, next player attacks
        refill_hands()                  # draw back up to 6
    """

    def __init__(self, player_names: list[str]):
        if len(player_names) < 2:
            raise ValueError("Need at least 2 players.")

        self.deck = Deck()
        self.players: list[Player] = [Player(n) for n in player_names]
        self.discard: list[Card] = []
        self.table = Table()
        self.phase = GamePhase.ATTACKING
        self.durak: Optional[Player] = None        # set at game end
        self.winners: list[Player] = []            # players who finished
        self.log: list[str] = []                   # human-readable event log

        self._deal_initial_hands()
        attacker_index = self._find_first_attacker()
        self.attacker_index: int = attacker_index
        self.defender_index: int = (attacker_index + 1) % len(self.players)
        self._log(f"Trump suit: {self.deck.trump_suit} (trump card: {self.deck.trump_card})")
        self._log(f"First attacker: {self.attacker.name}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def attacker(self) -> Player:
        return self.players[self.attacker_index]

    @property
    def defender(self) -> Player:
        return self.players[self.defender_index]

    @property
    def trump(self) -> str:
        return self.deck.trump_suit

    @property
    def active_players(self) -> list[Player]:
        return [p for p in self.players if p not in self.winners]

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _deal_initial_hands(self):
        for _ in range(HAND_SIZE):
            for p in self.players:
                p.draw_up_to(self.deck, HAND_SIZE)

    def _find_first_attacker(self) -> int:
        """Player with the lowest trump card goes first."""
        best_index, best_rank = 0, 999
        for i, p in enumerate(self.players):
            lt = p.lowest_trump(self.trump)
            if lt and lt.rank < best_rank:
                best_rank = lt.rank
                best_index = i
        return best_index

    # ------------------------------------------------------------------
    # Actions (called by UI / network layer)
    # ------------------------------------------------------------------

    def attack(self, player: Player, card: Card) -> dict:
        """
        Play an attack card.
        First attack must come from the attacker.
        Subsequent attacks (pile-ons) can come from any non-defender active player.
        Returns a result dict: {"ok": bool, "error": str or None}
        """
        if self.phase == GamePhase.GAME_OVER:
            return self._err("Game is over.")
        if player == self.defender:
            return self._err("The defender cannot attack.")
        if not player.has_card(card):
            return self._err(f"{player.name} does not have {card}.")

        # First card of the round
        if self.table.is_empty():
            if self.phase != GamePhase.ATTACKING:
                return self._err("Not the attack phase.")
            if player != self.attacker:
                return self._err(f"It is {self.attacker.name}'s turn to attack.")
        else:
            # Pile-on: rank must already be on the table
            if card.rank not in self.table.valid_pile_on_ranks():
                return self._err(f"Rank {card.rank_name} is not on the table; cannot pile on.")
            # Cannot pile on more cards than the defender has in hand
            if len(self.table.undefended()) >= len(self.defender.hand):
                return self._err("Cannot pile on: defender has no room.")

        player.remove_card(card)
        self.table.add_attack(card)
        self.phase = GamePhase.DEFENDING
        self._log(f"{player.name} attacks with {card}")
        return self._ok()

    def defend(self, player: Player, attack_card: Card, defense_card: Card) -> dict:
        """Defender plays a card to beat a specific attack card."""
        if self.phase != GamePhase.DEFENDING:
            return self._err("Not the defense phase.")
        if player != self.defender:
            return self._err(f"Only {self.defender.name} can defend.")
        if attack_card not in self.table.undefended():
            return self._err(f"{attack_card} is already defended or not on the table.")
        if not player.has_card(defense_card):
            return self._err(f"{player.name} does not have {defense_card}.")
        if not defense_card.beats(attack_card, self.trump):
            return self._err(f"{defense_card} cannot beat {attack_card}.")

        player.remove_card(defense_card)
        self.table.add_defense(attack_card, defense_card)
        self._log(f"{player.name} defends {attack_card} with {defense_card}")

        if self.table.all_defended():
            self.phase = GamePhase.PILE_ON
            self._log("All attacks defended. Attackers may pile on or end the attack.")

        return self._ok()

    def end_attack(self, player: Player) -> dict:
        """
        Attacker (or any non-defender) declares no more pile-ons.
        If all cards are defended → table cleared, rotate roles.
        If any undefended → defender picks up all table cards.
        """
        if self.phase not in (GamePhase.ATTACKING, GamePhase.DEFENDING, GamePhase.PILE_ON):
            return self._err("Cannot end attack in current phase.")
        if player == self.defender:
            return self._err("The defender cannot end the attack.")

        if not self.table.all_defended():
            # Defender picks up
            self._defender_picks_up()
        else:
            # Table cleared
            self._table_cleared()

        self._refill_hands()
        self._check_winners()

        if len(self.active_players) <= 1:
            self._end_game()
        else:
            self.phase = GamePhase.ATTACKING

        return self._ok()

    def defender_picks_up(self, player: Player) -> dict:
        """Defender voluntarily picks up (gives up defending)."""
        if player != self.defender:
            return self._err("Only the defender can pick up.")
        if self.phase != GamePhase.DEFENDING:
            return self._err("Not the defense phase.")
        self._defender_picks_up()
        self._refill_hands()
        self._check_winners()
        if len(self.active_players) <= 1:
            self._end_game()
        else:
            self.phase = GamePhase.ATTACKING
        return self._ok()

    def can_transfer(self) -> bool:
        """
        Transfer (Perevod) is possible when:
        1. The table has attack cards with none defended yet
        2. The defender holds at least one card matching every attack rank on the table
        Works in 1v1 (attack goes back to attacker) and 3+ players (goes to next player).
        """
        if not self.table.attacks:
            return False
        if len(self.table.defenses) > 0:
            return False  # cannot transfer once any card is defended
        attack_ranks = {c.rank for c in self.table.attacks}
        defender_ranks = {c.rank for c in self.defender.hand}
        return attack_ranks.issubset(defender_ranks)

    def _transfer_target_index(self) -> int:
        """Find the index of the player who receives the transferred attack."""
        # In 1v1 this wraps back to the attacker; in 3+ it goes to the next active player
        i = (self.defender_index + 1) % len(self.players)
        while self.players[i] in self.winners:
            i = (i + 1) % len(self.players)
        return i

    def transfer(self, player: Player, cards: list[Card]) -> dict:
        """
        Perevod: defender redirects the attack by playing cards of the SAME rank.
        - 1v1: attack goes back to the original attacker
        - 3+ players: attack passes to the next active player
        Rules:
        - Only allowed before any defense has been played this round
        - All cards played must match the rank(s) already on the table
        - New defender cannot receive more cards than their hand size
        """
        if self.phase != GamePhase.DEFENDING:
            return self._err("Transfer is only possible during the defense phase.")
        if player != self.defender:
            return self._err(f"Only {self.defender.name} can transfer the attack.")
        if len(self.table.defenses) > 0:
            return self._err("Cannot transfer after any card has been defended.")
        if not cards:
            return self._err("You must play at least one card to transfer.")

        # All transfer cards must match the rank(s) already on the table
        table_ranks = {c.rank for c in self.table.attacks}
        for c in cards:
            if not player.has_card(c):
                return self._err(f"{player.name} does not have {c}.")
            if c.rank not in table_ranks:
                return self._err(
                    f"{c} has rank {c.rank_name} — must match table ranks: "
                    f"{[RANK_NAMES[r] for r in table_ranks]}."
                )

        # Find who receives the attack
        new_defender_index = self._transfer_target_index()
        new_defender = self.players[new_defender_index]

        # New defender cannot receive more cards than they have in hand
        total_incoming = len(self.table.attacks) + len(cards)
        if total_incoming > len(new_defender.hand):
            return self._err(
                f"Cannot transfer: {new_defender.name} only has {len(new_defender.hand)} cards "
                f"but would receive {total_incoming} attack cards."
            )

        # Apply the transfer — add cards to table, rotate roles
        old_defender = self.defender
        old_defender_index = self.defender_index
        for c in cards:
            player.remove_card(c)
            self.table.add_attack(c)

        # Old defender becomes the attacker, new player becomes the defender
        self.attacker_index = old_defender_index
        self.defender_index = new_defender_index
        self._log(
            f"{old_defender.name} transfers the attack to {new_defender.name} "
            f"by playing {cards}"
        )
        self.phase = GamePhase.DEFENDING
        return self._ok()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _defender_picks_up(self):
        cards = self.table.all_cards()
        self.defender.add_cards(cards)
        self._log(f"{self.defender.name} picks up {cards}")
        self.table.clear()
        # Defender skips their attack turn: next attacker = player after defender
        skipped_defender_index = self.defender_index
        self.attacker_index = (skipped_defender_index + 1) % len(self.players)
        self.defender_index = (self.attacker_index + 1) % len(self.players)

    def _table_cleared(self):
        self._log(f"Table cleared. Cards go to discard.")
        self.discard.extend(self.table.all_cards())
        self.table.clear()
        # Defender becomes the next attacker
        self.attacker_index = self.defender_index
        self.defender_index = (self.attacker_index + 1) % len(self.players)

    def _refill_hands(self):
        """Refill in order: attacker, then clockwise, defender last."""
        order = []
        i = self.attacker_index
        while len(order) < len(self.players):
            if i != self.defender_index:
                order.append(i)
            i = (i + 1) % len(self.players)
        order.append(self.defender_index)
        for idx in order:
            self.players[idx].draw_up_to(self.deck)

    def _check_winners(self):
        """Players with empty hands when deck is empty have won."""
        if len(self.deck) == 0:
            for p in self.players:
                if p not in self.winners and p.is_out():
                    self.winners.append(p)
                    self._log(f"{p.name} is out of cards — they win!")

    def _end_game(self):
        remaining = [p for p in self.active_players if p not in self.winners]
        if remaining:
            self.durak = remaining[0]
            self._log(f"Game over! {self.durak.name} is the DURAK 🃏")
        else:
            self._log("Game over! Everyone escaped!")
        self.phase = GamePhase.GAME_OVER

    def _skip_finished_players(self):
        """Advance attacker/defender indices past players who have won."""
        active = set(self.active_players)
        # Advance attacker
        while self.attacker not in active:
            self.attacker_index = (self.attacker_index + 1) % len(self.players)
        # Advance defender
        self.defender_index = (self.attacker_index + 1) % len(self.players)
        while self.defender not in active:
            self.defender_index = (self.defender_index + 1) % len(self.players)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ok(self) -> dict:
        return {"ok": True, "error": None}

    def _err(self, msg: str) -> dict:
        self._log(f"ERROR: {msg}")
        return {"ok": False, "error": msg}

    def _log(self, msg: str):
        self.log.append(msg)
        print(f"[Durak] {msg}")

    def state_for_player(self, player: Player) -> dict:
        """
        Returns a JSON-serialisable snapshot of the game state
        from the perspective of a specific player.
        (Other players' hands are hidden.)
        """
        return {
            "trump": self.trump,
            "trump_card": str(self.deck.trump_card),
            "deck_size": len(self.deck),
            "phase": self.phase.value,
            "attacker": self.attacker.name,
            "defender": self.defender.name,
            "table": {str(k): str(v) for k, v in self.table.defenses.items()} |
                     {str(k): None for k in self.table.undefended()},
            "your_hand": [str(c) for c in player.hand],
            "opponents": {
                p.name: len(p.hand)
                for p in self.players if p != player
            },
            "winners": [p.name for p in self.winners],
            "durak": self.durak.name if self.durak else None,
        }


# ---------------------------------------------------------------------------
# Quick self-test (run: python game_engine.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Durak Engine Self-Test ===\n")
    gs = GameState(["Alice", "Bob"])
    alice, bob = gs.players

    print(f"\nTrump: {gs.trump}")
    print(f"Alice's hand: {alice.hand}")
    print(f"Bob's hand:   {bob.hand}")
    print(f"Attacker: {gs.attacker.name}, Defender: {gs.defender.name}\n")

    # Attacker attacks with their first card
    if True:
        attacker_player = gs.attacker
        defender_player = gs.defender
        atk_card = attacker_player.hand[0]
        result = gs.attack(attacker_player, atk_card)
        print(f"Attack result: {result}")
        print(f"Table: {gs.table}\n")

        # Defender tries to defend
        defended = False
        for def_card in defender_player.hand:
            if def_card.beats(atk_card, gs.trump):
                result = gs.defend(defender_player, atk_card, def_card)
                print(f"Defend result: {result}")
                defended = True
                break
        if not defended:
            print(f"{defender_player.name} cannot defend — picking up.")
            gs.defender_picks_up(defender_player)

        # End the attack
        gs.end_attack(attacker_player)
        print(f"\nAfter round:")
        print(f"Alice's hand: {alice.hand}")
        print(f"Bob's hand:   {bob.hand}")
        print(f"Deck size: {len(gs.deck)}")
        print(f"Phase: {gs.phase}")
