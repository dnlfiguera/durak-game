"""
terminal_game.py
================
Interactive 2-player Durak in the terminal.
Both players sit at the same keyboard (pass-and-play).
Defender's hand is hidden between turns for privacy.

Run:  python terminal_game.py
"""

import os
from game_engine import GameState, GamePhase, Card, RANK_NAMES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def pause(msg="Press Enter to continue..."):
    input(f"\n  {msg}")

def separator(char="─", width=52):
    print(char * width)

def header(title: str):
    separator("═")
    print(f"  🃏  {title}")
    separator("═")

def show_hand(player, trump: str):
    """Print a player's hand with numbered options."""
    print(f"\n  {player.name}'s hand ({len(player.hand)} cards):")
    for i, card in enumerate(player.hand):
        trump_marker = " 🌟" if card.suit == trump else ""
        print(f"    [{i}] {card}{trump_marker}")

def show_table(table, trump: str):
    """Print the current table state."""
    if table.is_empty():
        print("  Table: (empty)")
        return
    print("  Table:")
    for atk in table.attacks:
        dfn = table.defenses.get(atk)
        trump_a = "🌟" if atk.suit == trump else "  "
        if dfn:
            trump_d = "🌟" if dfn.suit == trump else "  "
            print(f"    {trump_a}{atk}  →  {trump_d}{dfn}  ✅")
        else:
            print(f"    {trump_a}{atk}  →  ???  ⚔️")

def show_status(gs: GameState):
    """Print game status bar."""
    separator()
    print(f"  Trump: {gs.trump}  |  Deck: {len(gs.deck)} cards  |  Discard: {len(gs.discard)} cards")
    print(f"  ⚔️  Attacker: {gs.attacker.name}   🛡️  Defender: {gs.defender.name}")
    separator()

def pick_card(player, prompt: str, trump: str) -> Card:
    """Ask the player to pick a card by index. Returns the Card."""
    show_hand(player, trump)
    while True:
        raw = input(f"\n  {prompt} (number, or 'q' to quit): ").strip().lower()
        if raw == "q":
            print("\n  Thanks for playing! 👋")
            exit()
        try:
            idx = int(raw)
            if 0 <= idx < len(player.hand):
                return player.hand[idx]
            else:
                print(f"  ❌ Pick a number between 0 and {len(player.hand)-1}.")
        except ValueError:
            print("  ❌ Please enter a number.")

def pick_attack_card_from_table(table, trump: str) -> Card:
    """Ask which undefended table card the defender should beat."""
    undefended = table.undefended()
    if len(undefended) == 1:
        return undefended[0]
    print("\n  Undefended cards on table:")
    for i, c in enumerate(undefended):
        t = "🌟" if c.suit == trump else "  "
        print(f"    [{i}] {t}{c}")
    while True:
        raw = input("  Which card to defend against? (number): ").strip()
        try:
            idx = int(raw)
            if 0 <= idx < len(undefended):
                return undefended[idx]
        except ValueError:
            pass
        print("  ❌ Invalid choice.")

def hidden_switch(to_player):
    """Screen privacy pause between players."""
    clear()
    print(f"\n  👀  Switching to {to_player.name}...")
    pause(f"When {to_player.name} is ready, press Enter.")
    clear()

# ---------------------------------------------------------------------------
# Turn logic
# ---------------------------------------------------------------------------

def attacker_turn(gs: GameState):
    attacker = gs.attacker

    clear()
    header(f"ATTACK — {attacker.name}'s turn")
    show_status(gs)
    show_table(gs.table, gs.trump)

    if gs.table.is_empty():
        print(f"\n  Play your first attack card against {gs.defender.name}.")
        card = pick_card(attacker, "Choose card to attack with", gs.trump)
        result = gs.attack(attacker, card)
        if not result["ok"]:
            print(f"  ❌ {result['error']}")
            pause()
            attacker_turn(gs)
    else:
        valid_ranks = sorted(gs.table.valid_pile_on_ranks())

        # Show hand with pile-on eligibility clearly marked
        print(f"\n  {attacker.name}'s hand ({len(attacker.hand)} cards):")
        playable = []
        for i, card in enumerate(attacker.hand):
            trump_marker = " 🌟" if card.suit == gs.trump else ""
            if card.rank in valid_ranks:
                print(f"    [{i}] {card}{trump_marker}  ✅ can pile on")
                playable.append(i)
            else:
                print(f"    [{i}] {card}{trump_marker}")

        if not playable:
            print(f"\n  ⚠️  No cards to pile on (need ranks: {valid_ranks}). Ending attack.")
            pause()
            gs.end_attack(attacker)
            return

        print(f"\n  Valid pile-on ranks: {valid_ranks}")
        while True:
            choice = input("  [p] Pile on more cards  |  [e] End attack: ").strip().lower()
            if choice in {"p", "e"}:
                break
            print("  ❌ Please type p or e.")
        if choice != "p":
            result = gs.end_attack(attacker)
            if not result["ok"]:
                print(f"  ❌ {result['error']}")
                pause()
        else:
            # Only offer valid cards
            print(f"\n  Choose a card marked ✅ to pile on:")
            while True:
                raw = input("  Card number (or 'c' to cancel and end attack): ").strip().lower()
                if raw == "c":
                    gs.end_attack(attacker)
                    return
                try:
                    idx = int(raw)
                    if idx not in playable:
                        print(f"  ❌ That card can't be piled on. Choose one marked ✅.")
                        continue
                    card = attacker.hand[idx]
                    result = gs.attack(attacker, card)
                    if not result["ok"]:
                        print(f"  ❌ {result['error']}")
                    break
                except ValueError:
                    print("  ❌ Enter a number, or 'c' to cancel.")


def defender_turn(gs: GameState):
    defender = gs.defender

    hidden_switch(defender)
    header(f"DEFEND — {defender.name}'s turn")
    show_status(gs)
    show_table(gs.table, gs.trump)

    undefended = gs.table.undefended()

    # Build transfer info
    can_transfer = gs.can_transfer()
    next_defender = None
    if can_transfer:
        nd_idx = gs._transfer_target_index()
        next_defender = gs.players[nd_idx]

    # Show hand with annotations BEFORE the menu
    attack_ranks = {c.rank for c in gs.table.attacks}
    print(f"\n  {defender.name}'s hand ({len(defender.hand)} cards):")
    for i, card in enumerate(defender.hand):
        trump_marker = " 🌟" if card.suit == gs.trump else ""
        tags = []
        for atk in undefended:
            if card.beats(atk, gs.trump):
                tags.append(f"beats {atk}")
        if card.rank in attack_ranks:
            tags.append(f"↩️ transfer to {next_defender.name}" if can_transfer else "↩️ transfer")
        tag_str = "  — " + ", ".join(tags) if tags else ""
        print(f"    [{i}] {card}{trump_marker}{tag_str}")

    print(f"\n  You must defend {len(undefended)} card(s).")
    menu = "  [d] Defend a card  |  [p] Pick up all cards"
    if can_transfer:
        menu += f"  |  [t] Transfer to {next_defender.name}"
    valid_choices = {"d", "p", "t"} if can_transfer else {"d", "p"}
    while True:
        choice = input(menu + ": ").strip().lower()
        if choice in valid_choices:
            break
        print(f"  ❌ Please type d, p{', or t' if can_transfer else ''}.")

    # ── Pick up ──
    if choice == "p":
        result = gs.defender_picks_up(defender)
        if result["ok"]:
            print(f"\n  {defender.name} picks up all table cards.")
        else:
            print(f"  ❌ {result['error']}")
        pause()
        return

    # ── Transfer (Perevod) ──
    if choice == "t":
        if not can_transfer:
            print("  ❌ Transfer is not available right now.")
            pause()
            defender_turn(gs)
            return

        table_ranks = sorted({c.rank for c in gs.table.attacks})
        print(f"\n  Transfer: play cards of rank(s) {[RANK_NAMES[r] for r in table_ranks]} "
              f"to pass the attack to {next_defender.name}.")
        print("  You can play multiple cards (one per line). Enter blank line when done.")

        transfer_cards = []
        show_hand(defender, gs.trump)
        while True:
            raw = input("  Card number to add (or Enter to confirm): ").strip()
            if raw == "":
                if not transfer_cards:
                    print("  ❌ You must play at least one card.")
                    continue
                break
            try:
                idx = int(raw)
                if 0 <= idx < len(defender.hand):
                    card = defender.hand[idx]
                    if card not in transfer_cards:
                        transfer_cards.append(card)
                        print(f"  + Added {card}")
                    else:
                        print("  Already added that card.")
                else:
                    print(f"  ❌ Pick 0–{len(defender.hand)-1}.")
            except ValueError:
                print("  ❌ Enter a number.")

        result = gs.transfer(defender, transfer_cards)
        if not result["ok"]:
            print(f"  ❌ {result['error']}")
            pause()
            defender_turn(gs)
        else:
            print(f"\n  ↩️  Attack transferred to {next_defender.name}!")
            pause()
        return

    # ── Defend one card ──
    atk_card = pick_attack_card_from_table(gs.table, gs.trump)

    # Show only cards that can legally beat the attack card
    print(f"\n  {defender.name}'s hand — choose a card to beat {atk_card}:")
    beatable = []
    for i, card in enumerate(defender.hand):
        trump_marker = " 🌟" if card.suit == gs.trump else ""
        if card.beats(atk_card, gs.trump):
            print(f"    [{i}] {card}{trump_marker}  ✅ can beat {atk_card}")
            beatable.append(i)
        elif card.rank == atk_card.rank:
            print(f"    [{i}] {card}{trump_marker}  ⚠️ same rank — use transfer, not defense")
        else:
            print(f"    [{i}] {card}{trump_marker}")

    if not beatable:
        print(f"\n  ⚠️  No card can beat {atk_card}. You must pick up.")
        pause()
        result = gs.defender_picks_up(defender)
        return

    while True:
        raw = input(f"\n  Card number to beat {atk_card} (or 'c' to pick up instead): ").strip().lower()
        if raw == "c":
            gs.defender_picks_up(defender)
            print(f"\n  {defender.name} picks up all table cards.")
            pause()
            return
        try:
            idx = int(raw)
            if idx not in beatable:
                print(f"  ❌ That card can't beat {atk_card}. Choose one marked ✅.")
                continue
            def_card = defender.hand[idx]
            break
        except ValueError:
            print("  ❌ Enter a number, or 'c' to pick up.")

    result = gs.defend(defender, atk_card, def_card)
    if not result["ok"]:
        print(f"  ❌ {result['error']}")
        pause()
        defender_turn(gs)
    else:
        print(f"\n  ✅ {def_card} beats {atk_card}!")
        if gs.table.all_defended():
            print(f"  All attacks defended! Attacker may pile on or end.")
        pause()


def pile_on_turn(gs: GameState):
    """After all cards defended, ask attacker to pile on or end."""
    attacker = gs.attacker
    hidden_switch(attacker)
    header(f"PILE ON? — {attacker.name}'s turn")
    show_status(gs)
    show_table(gs.table, gs.trump)

    valid_ranks = sorted(gs.table.valid_pile_on_ranks())

    # Show hand with pile-on eligibility clearly marked
    print(f"\n  {attacker.name}'s hand ({len(attacker.hand)} cards):")
    playable = []
    for i, card in enumerate(attacker.hand):
        trump_marker = " 🌟" if card.suit == gs.trump else ""
        if card.rank in valid_ranks:
            print(f"    [{i}] {card}{trump_marker}  ✅ can pile on")
            playable.append(i)
        else:
            print(f"    [{i}] {card}{trump_marker}")

    if not playable:
        print(f"\n  ⚠️  No cards to pile on (need ranks: {valid_ranks}). Ending attack.")
        pause()
        gs.end_attack(attacker)
        return

    print(f"\n  Valid pile-on ranks: {valid_ranks}")
    while True:
        choice = input("  [p] Pile on more cards  |  [e] End attack: ").strip().lower()
        if choice in {"p", "e"}:
            break
        print("  ❌ Please type p or e.")

    if choice != "p":
        result = gs.end_attack(attacker)
        if not result["ok"]:
            print(f"  ❌ {result['error']}")
            pause()
    else:
        print(f"\n  Choose a card marked ✅ to pile on:")
        while True:
            raw = input("  Card number (or 'c' to cancel and end attack): ").strip().lower()
            if raw == "c":
                gs.end_attack(attacker)
                return
            try:
                idx = int(raw)
                if idx not in playable:
                    print(f"  ❌ That card can't be piled on. Choose one marked ✅.")
                    continue
                card = attacker.hand[idx]
                result = gs.attack(attacker, card)
                if not result["ok"]:
                    print(f"  ❌ {result['error']}")
                break
            except ValueError:
                print("  ❌ Enter a number, or 'c' to cancel.")


def show_round_result(gs: GameState):
    """Show the last few log lines after a round ends."""
    clear()
    separator("═")
    print("  📋  ROUND RESULT")
    separator("═")
    for line in gs.log[-5:]:
        print(f"  {line}")
    pause()

# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

def game_loop(gs: GameState):
    last_phase = gs.phase

    while gs.phase != GamePhase.GAME_OVER:
        current_phase = gs.phase

        if current_phase == GamePhase.ATTACKING:
            attacker_turn(gs)

        elif current_phase == GamePhase.DEFENDING:
            defender_turn(gs)

        elif current_phase == GamePhase.PILE_ON:
            pile_on_turn(gs)

        # Detect end of round (phase reset to ATTACKING from something else)
        if gs.phase == GamePhase.ATTACKING and current_phase != GamePhase.ATTACKING:
            show_round_result(gs)

        last_phase = gs.phase

    # ── Game over screen ──
    clear()
    header("GAME OVER")
    if gs.durak:
        print(f"\n  🃏  {gs.durak.name} is the DURAK!\n")
    for p in gs.winners:
        print(f"  🏆  {p.name} escaped the game!")
    separator("═")
    print("\n  Full game log:")
    for line in gs.log:
        print(f"    {line}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    clear()
    header("DURAK — Terminal Edition")
    print("""
  Rules reminder:
  • Trump suit beats any non-trump card
  • To defend: same suit + higher rank, OR any trump card
  • Can't defend? Pick up all table cards
  • Transfer (Perevod): if attacked with a 6, play your own 6(s) to pass
    the attack to the next player — only before defending anything,
    only with 3+ players
  • Deck refills to 6 cards after each round
  • Empty your hand when deck is gone = you WIN
  • Last player with cards = DURAK 🃏
    """)

    p1 = input("  Player 1 name: ").strip() or "Alice"
    p2 = input("  Player 2 name: ").strip() or "Bob"
    pause("Game starting! Press Enter...")

    gs = GameState([p1, p2])
    game_loop(gs)

if __name__ == "__main__":
    main()
