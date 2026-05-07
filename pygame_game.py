"""
pygame_game.py
==============
Pygame visual Durak - Step 3.
Pass-and-play on one screen for now.
Layout:
  - Opponent hand (card backs)  <- top
  - Table (attack/defense pairs) <- middle
  - Trump card + deck            <- right side
  - Your hand (face up, clickable) <- bottom
  - Action buttons               <- bottom bar

Run:  python pygame_game.py
Requires: pip install pygame
"""

import pygame
import sys
from game_engine import GameState, GamePhase, Card, RANK_NAMES

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SW, SH = 1024, 800          # screen width / height
FPS = 60

# Card dimensions
CW, CH = 70, 100            # card width / height
CARD_GAP = 12               # gap between cards in hand

# Colors
C_BG         = (34, 100, 34)    # green felt
C_CARD_FRONT = (255, 252, 240)  # cream
C_CARD_BACK  = (30, 80, 160)    # blue back
C_CARD_SEL   = (255, 220, 50)   # yellow selected
C_CARD_VALID = (100, 220, 100)  # green tint = valid move
C_TRUMP_GLOW = (255, 200, 0)    # gold border for trump cards
C_TEXT_DARK  = (20, 20, 20)
C_TEXT_LIGHT = (240, 240, 240)
C_RED        = (200, 30, 30)
C_BLACK      = (20, 20, 20)
C_BTN        = (50, 50, 80)
C_BTN_HOV    = (80, 80, 130)
C_BTN_DIS    = (80, 80, 80)
C_PANEL      = (0, 0, 0, 140)   # semi-transparent overlay

SUIT_COLOR = {"♠": C_BLACK, "♣": C_BLACK, "♥": C_RED, "♦": C_RED}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def draw_card(surf, x, y, card: Card, trump: str,
              selected=False, valid=False, face_up=True):
    """Draw a single card rectangle at (x, y)."""
    rect = pygame.Rect(x, y, CW, CH)

    # Shadow
    shadow = pygame.Rect(x + 3, y + 3, CW, CH)
    pygame.draw.rect(surf, (0, 0, 0, 80), shadow, border_radius=6)

    # Trump glow
    if face_up and card.suit == trump:
        glow = pygame.Rect(x - 3, y - 3, CW + 6, CH + 6)
        pygame.draw.rect(surf, C_TRUMP_GLOW, glow, border_radius=8)

    # Card body
    if selected:
        pygame.draw.rect(surf, C_CARD_SEL, rect, border_radius=6)
    elif valid:
        pygame.draw.rect(surf, C_CARD_VALID, rect, border_radius=6)
    elif face_up:
        pygame.draw.rect(surf, C_CARD_FRONT, rect, border_radius=6)
    else:
        pygame.draw.rect(surf, C_CARD_BACK, rect, border_radius=6)
        # Back pattern
        inner = pygame.Rect(x + 5, y + 5, CW - 10, CH - 10)
        pygame.draw.rect(surf, (20, 60, 130), inner, border_radius=4)
        pygame.draw.rect(surf, (255, 255, 255), inner, 1, border_radius=4)
        return

    # Border
    pygame.draw.rect(surf, (180, 180, 160), rect, 2, border_radius=6)

    # Suit + rank text
    font_big  = pygame.font.SysFont("arial", 22, bold=True)
    font_small = pygame.font.SysFont("arial", 14)
    color = SUIT_COLOR.get(card.suit, C_BLACK)

    rank_surf = font_big.render(card.rank_name, True, color)
    suit_surf = font_small.render(card.suit, True, color)

    surf.blit(rank_surf, (x + 5, y + 4))
    surf.blit(suit_surf, (x + 5, y + 24))

    # Mirror bottom-right
    rank_surf2 = pygame.transform.rotate(rank_surf, 180)
    suit_surf2 = pygame.transform.rotate(suit_surf, 180)
    surf.blit(rank_surf2, (x + CW - rank_surf.get_width() - 5, y + CH - 40))
    surf.blit(suit_surf2, (x + CW - suit_surf.get_width() - 5, y + CH - 22))

    # Center suit (big)
    font_center = pygame.font.SysFont("arial", 32, bold=True)
    cs = font_center.render(card.suit, True, color)
    surf.blit(cs, (x + CW // 2 - cs.get_width() // 2,
                   y + CH // 2 - cs.get_height() // 2))


def draw_button(surf, rect, label, enabled=True, hovered=False, font=None):
    color = C_BTN_HOV if hovered and enabled else (C_BTN if enabled else C_BTN_DIS)
    pygame.draw.rect(surf, color, rect, border_radius=8)
    pygame.draw.rect(surf, (200, 200, 200), rect, 2, border_radius=8)
    if font is None:
        font = pygame.font.SysFont("arial", 18, bold=True)
    txt = font.render(label, True, C_TEXT_LIGHT if enabled else (140, 140, 140))
    surf.blit(txt, (rect.centerx - txt.get_width() // 2,
                    rect.centery - txt.get_height() // 2))


def text(surf, msg, x, y, size=18, color=C_TEXT_LIGHT, bold=False, center=False):
    font = pygame.font.SysFont("arial", size, bold=bold)
    s = font.render(str(msg), True, color)
    if center:
        x -= s.get_width() // 2
    surf.blit(s, (x, y))
    return s.get_width()


def hand_x_start(n_cards):
    """Left x so that n_cards are centered on screen."""
    total = n_cards * CW + (n_cards - 1) * CARD_GAP
    return SW // 2 - total // 2


# ---------------------------------------------------------------------------
# Game screen (pass-and-play)
# ---------------------------------------------------------------------------

class PrivacyScreen:
    """Shown between turns so the next player can sit down."""
    def __init__(self, player_name: str):
        self.player_name = player_name
        self.done = False

    def handle(self, event):
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self.done = True

    def draw(self, surf):
        surf.fill((10, 10, 40))
        text(surf, f"Pass the screen to  {self.player_name}", SW // 2, SH // 2 - 60,
             size=32, bold=True, center=True)
        text(surf, "Press any key or click when ready...", SW // 2, SH // 2 + 10,
             size=22, center=True, color=(180, 180, 180))


class DurakGame:
    def __init__(self, screen, names):
        self.screen = screen
        self.gs = GameState(names)
        self.font = pygame.font.SysFont("arial", 18)

        # UI state
        self.selected: Card | None = None       # card clicked in hand
        self.selected_atk: Card | None = None   # undefended table card chosen for defense
        self.transfer_cards: list[Card] = []    # cards chosen for transfer
        self.message = ""                        # feedback message at bottom
        self.privacy: PrivacyScreen | None = None

        # Which player is "us" right now (pass-and-play: switches each turn)
        self.current_player_index = self.gs.attacker_index
        self._show_privacy(self.gs.attacker)

    # ------------------------------------------------------------------
    # Privacy switch
    # ------------------------------------------------------------------

    def _show_privacy(self, player):
        self.privacy = PrivacyScreen(player.name)
        self.selected = None
        self.selected_atk = None
        self.transfer_cards = []
        self.message = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def me(self):
        return self.gs.players[self.current_player_index]

    @property
    def phase(self):
        return self.gs.phase

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if self.privacy:
            self.privacy.handle(event)
            if self.privacy.done:
                self.privacy = None
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._on_click(event.pos)

    def _on_click(self, pos):
        gs = self.gs

        # -- Button clicks --
        for label, rect, action in self._buttons():
            if rect.collidepoint(pos):
                action()
                return

        # -- Card in my hand --
        my_hand = self.me.hand
        sx = hand_x_start(len(my_hand))
        for i, card in enumerate(my_hand):
            cx = sx + i * (CW + CARD_GAP)
            cy = SH - CH - 120
            if pygame.Rect(cx, cy, CW, CH).collidepoint(pos):
                self._on_card_click(card)
                return

        # -- Undefended table card (for defense targeting) --
        if gs.phase == GamePhase.DEFENDING and self.me == gs.defender:
            for i, atk in enumerate(gs.table.attacks):
                if atk in gs.table.defenses:
                    continue
                tx, ty = self._table_card_pos(i, defense=False)
                if pygame.Rect(tx, ty, CW, CH).collidepoint(pos):
                    if self.selected is not None:
                        # Hand card already selected — try to defend immediately
                        result = gs.defend(self.me, atk, self.selected)
                        self._handle_result(result)
                        if result["ok"]:
                            self.selected_atk = None
                            self.selected = None
                            self._after_action()
                    else:
                        # No hand card selected yet — set target first
                        self.selected_atk = atk
                        self.message = f"Now pick a card from your hand to beat {atk}"
                    return

    def _on_card_click(self, card: Card):
        gs = self.gs
        phase = gs.phase

        # ATTACKING / PILE_ON - play attack card
        if phase == GamePhase.ATTACKING and self.me == gs.attacker:
            result = gs.attack(self.me, card)
            self._handle_result(result)
            if result["ok"]:
                self.selected = None
                self._after_action()

        elif phase == GamePhase.PILE_ON and self.me != gs.defender:
            result = gs.attack(self.me, card)
            self._handle_result(result)
            if result["ok"]:
                self.selected = None
                self._after_action()

        # DEFENDING - select card first, then either defend or transfer
        elif phase == GamePhase.DEFENDING and self.me == gs.defender:
            # First click selects the card
            if self.selected != card:
                self.selected = card
                # Show what this card can do
                attack_ranks = {c.rank for c in gs.table.attacks}
                can_beat = [a for a in gs.table.undefended() if card.beats(a, gs.trump)]
                can_transfer = card.rank in attack_ranks and gs.can_transfer()
                if can_beat:
                    self.message = f"Selected {card} - click an attack card on table to defend it"
                elif can_transfer:
                    tgt = gs.players[gs._transfer_target_index()]
                    self.message = f"Selected {card} - press Transfer->{tgt.name} button"
                else:
                    self.message = f"{card} cannot beat any attack card"
                return

            # Second click on same card = deselect
            if self.selected == card and self.selected_atk is None:
                self.selected = None
                self.message = ""
                return

            # Card already selected + table target selected = defend
            if self.selected_atk is not None:
                result = gs.defend(self.me, self.selected_atk, card)
                self._handle_result(result)
                if result["ok"]:
                    self.selected_atk = None
                    self.selected = None
                    self._after_action()

        else:
            self.message = "It's not your turn to play that."

    def _handle_result(self, result):
        if not result["ok"]:
            self.message = f"X  {result['error']}"
        else:
            self.message = ""

    def _after_action(self):
        """Called after any successful action - switch screen to correct player."""
        gs = self.gs
        if gs.phase == GamePhase.GAME_OVER:
            return
        if gs.phase == GamePhase.DEFENDING:
            # Switch to defender
            self.current_player_index = gs.defender_index
            self._show_privacy(gs.defender)
        elif gs.phase == GamePhase.ATTACKING:
            # Switch to attacker (new round)
            self.current_player_index = gs.attacker_index
            self._show_privacy(gs.attacker)
        elif gs.phase == GamePhase.PILE_ON:
            # All cards defended - attacker decides to pile on or end
            # Only switch if current player is NOT already the attacker
            if self.current_player_index != gs.attacker_index:
                self.current_player_index = gs.attacker_index
                self._show_privacy(gs.attacker)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _buttons(self):
        """Return list of (label, Rect, callback) for currently valid buttons."""
        gs = self.gs
        phase = gs.phase
        buttons = []
        bw, bh = 160, 44
        by = SH - 160
        bx = SW - bw - 20

        if phase == GamePhase.ATTACKING and self.me == gs.attacker:
            pass  # no buttons needed - just click a card

        if phase == GamePhase.DEFENDING and self.me == gs.defender:
            # Pick up
            r = pygame.Rect(bx, by, bw, bh)
            buttons.append(("Pick up", r, self._action_pickup))
            # Transfer
            if gs.can_transfer():
                r2 = pygame.Rect(bx, by + bh + 10, bw, bh)
                tgt = gs.players[gs._transfer_target_index()]
                buttons.append((f"Transfer->{tgt.name}", r2, self._action_transfer))

        if phase == GamePhase.PILE_ON and self.me == gs.attacker:
            r = pygame.Rect(bx, by, bw, bh)
            buttons.append(("End Attack", r, self._action_end_attack))

        return buttons

    def _action_pickup(self):
        result = self.gs.defender_picks_up(self.me)
        self._handle_result(result)
        if result["ok"]:
            self._after_action()

    def _action_end_attack(self):
        result = self.gs.end_attack(self.me)
        self._handle_result(result)
        if result["ok"]:
            self._after_action()

    def _action_transfer(self):
        """Transfer: play selected card as redirect."""
        if self.selected is None:
            self.message = "Click a same-rank card in your hand first, then press Transfer"
            return
        result = self.gs.transfer(self.me, [self.selected])
        self._handle_result(result)
        if result["ok"]:
            self.selected = None
            self.selected_atk = None
            # After transfer phase is still DEFENDING - switch to new defender
            self._after_action()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self):
        surf = self.screen
        gs = self.gs

        if self.privacy:
            self.privacy.draw(surf)
            return

        surf.fill(C_BG)

        self._draw_status()
        self._draw_opponent()
        self._draw_deck()
        self._draw_table()
        self._draw_my_hand()
        self._draw_buttons()
        self._draw_message()

        if gs.phase == GamePhase.GAME_OVER:
            self._draw_game_over()

    def _draw_status(self):
        gs = self.gs
        trump_color = SUIT_COLOR.get(gs.trump, C_TEXT_LIGHT)
        text(self.screen, f"Trump: {gs.trump}", 20, 14, size=20,
             color=C_TRUMP_GLOW, bold=True)
        text(self.screen, f"Deck: {len(gs.deck)}", 130, 14, size=18)
        text(self.screen, f"Discard: {len(gs.discard)}", 230, 14, size=18)
        text(self.screen, f"ATK: {gs.attacker.name}", 380, 14,
             size=18, color=(255, 180, 80), bold=True)
        text(self.screen, f"DEF: {gs.defender.name}", 530, 14,
             size=18, color=(100, 200, 255), bold=True)
        text(self.screen, f"Phase: {gs.phase.value}", 700, 14, size=16,
             color=(180, 180, 180))

    def _draw_opponent(self):
        """Draw opponent's hand face-down at the top."""
        gs = self.gs
        opponent = [p for p in gs.players if p != self.me]
        if not opponent:
            return
        opp = opponent[0]
        n = len(opp.hand)
        sx = hand_x_start(n)
        text(self.screen, f"{opp.name}  ({n} cards)",
             SW // 2, 50, size=16, color=(200, 200, 200), center=True)
        for i in range(n):
            cx = sx + i * (CW + CARD_GAP)
            draw_card(self.screen, cx, 70, opp.hand[i], gs.trump, face_up=False)

    def _draw_deck(self):
        """Draw trump card and deck stack on the right."""
        gs = self.gs
        dx = SW - CW - 30
        # Deck stack
        for i in range(min(len(gs.deck), 5)):
            draw_card(self.screen, dx - i * 2, SH // 2 - CH // 2 - i * 2,
                      gs.deck.trump_card, gs.trump, face_up=False)
        text(self.screen, str(len(gs.deck)), dx + CW // 2, SH // 2 + CH // 2 - 60 + 10,
             size=16, center=True)
        # Trump card (rotated look - just draw sideways offset)
        if len(gs.deck) > 0:
            draw_card(self.screen, dx - CW // 2 - 10, SH // 2 - CH // 2 + 20,
                      gs.deck.trump_card, gs.trump, face_up=True)
            text(self.screen, "trump", dx - CW // 2 - 10 + CW // 2,
                 SH // 2 - CH // 2 + 20 + CH + 4, size=13,
                 color=C_TRUMP_GLOW, center=True)

    def _table_card_pos(self, index, defense=False):
        """Position for a table card (attack or defense)."""
        n_pairs = len(self.gs.table.attacks)
        total_w = n_pairs * (CW * 2 + 10) + (n_pairs - 1) * 20
        sx = SW // 2 - total_w // 2
        pair_x = sx + index * (CW * 2 + 30)
        ty = SH // 2 - CH // 2
        if defense:
            return pair_x + CW + 10, ty - 10
        return pair_x, ty

    def _draw_table(self):
        gs = self.gs
        # Label
        text(self.screen, "Table", SW // 2, SH // 2 - CH // 2 - 24,
             size=15, color=(180, 220, 180), center=True)

        for i, atk in enumerate(gs.table.attacks):
            ax, ay = self._table_card_pos(i, defense=False)
            is_sel = (self.selected_atk == atk)
            draw_card(self.screen, ax, ay, atk, gs.trump, selected=is_sel)

            dfn = gs.table.defenses.get(atk)
            if dfn:
                dx2, dy2 = self._table_card_pos(i, defense=True)
                draw_card(self.screen, dx2, dy2, dfn, gs.trump)
            else:
                # "???" placeholder
                r = pygame.Rect(*self._table_card_pos(i, defense=True), CW, CH)
                pygame.draw.rect(self.screen, (60, 60, 60), r, 2, border_radius=6)
                text(self.screen, "?", r.centerx, r.centery - 10,
                     size=22, color=(120, 120, 120), center=True)

    def _draw_my_hand(self):
        gs = self.gs
        me = self.me
        phase = gs.phase
        hand = me.hand
        sx = hand_x_start(len(hand))
        cy = SH - CH - 120

        # Label
        text(self.screen, f"Your hand - {me.name}", SW // 2, cy - 22,
             size=15, color=(220, 220, 180), center=True)

        attack_ranks = {c.rank for c in gs.table.attacks}

        for i, card in enumerate(hand):
            cx = sx + i * (CW + CARD_GAP)
            selected = (card == self.selected)

            # Highlight valid moves
            valid = False
            if phase == GamePhase.ATTACKING and me == gs.attacker and gs.table.is_empty():
                valid = True
            elif phase in (GamePhase.ATTACKING, GamePhase.PILE_ON) and me != gs.defender:
                valid = card.rank in attack_ranks
            elif phase == GamePhase.DEFENDING and me == gs.defender:
                can_beat = any(card.beats(a, gs.trump) for a in gs.table.undefended())
                can_transfer = card.rank in attack_ranks and gs.can_transfer()
                if self.selected_atk:
                    valid = card.beats(self.selected_atk, gs.trump)
                else:
                    valid = can_beat or can_transfer

            # Lift selected card
            draw_y = cy - 15 if selected else cy
            draw_card(self.screen, cx, draw_y, card, gs.trump,
                      selected=selected, valid=valid)

            # Click toggles selection
            if pygame.mouse.get_pressed()[0]:
                pass  # handled in event

    def _draw_buttons(self):
        mx, my = pygame.mouse.get_pos()
        for label, rect, action in self._buttons():
            hovered = rect.collidepoint(mx, my)
            draw_button(self.screen, rect, label, hovered=hovered)

    def _draw_message(self):
        gs = self.gs
        # Dark info bar at the very bottom
        bar_h = 56
        bar_rect = pygame.Rect(0, SH - bar_h, SW, bar_h)
        pygame.draw.rect(self.screen, (15, 15, 15), bar_rect)
        pygame.draw.line(self.screen, (80, 80, 80), (0, SH - bar_h), (SW, SH - bar_h), 1)

        # Hint line (top of bar)
        hint = self.message
        if not hint:
            if gs.phase == GamePhase.ATTACKING and self.me == gs.attacker:
                hint = "Your turn to attack  -  click a card to play it"
            elif gs.phase == GamePhase.DEFENDING and self.me == gs.defender:
                if self.selected_atk:
                    hint = f"Now pick a card from your hand to beat  {self.selected_atk}"
                else:
                    hint = "Click an attack card on the table, then pick your defense card"
            elif gs.phase == GamePhase.PILE_ON and self.me == gs.attacker:
                hint = "Click a card to pile on  -  or press End Attack"

        hint_color = (255, 100, 100) if self.message else (255, 210, 80)
        text(self.screen, hint, SW // 2, SH - bar_h + 10,
             size=17, color=hint_color, center=True)

        # Sub-line: whose turn
        sub = f"Playing as:  {self.me.name}   |   Phase:  {gs.phase.value}   |   Deck: {len(gs.deck)}"
        text(self.screen, sub, SW // 2, SH - bar_h + 32,
             size=14, color=(160, 160, 160), center=True)

    def _draw_game_over(self):
        overlay = pygame.Surface((SW, SH), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        gs = self.gs
        if gs.durak:
            text(self.screen, f"{gs.durak.name} is the DURAK!", SW // 2, SH // 2 - 40,
                 size=42, bold=True, color=(255, 80, 80), center=True)
        for i, p in enumerate(gs.winners):
            text(self.screen, f"{p.name} escaped!", SW // 2, SH // 2 + 20 + i * 36,
                 size=28, color=(255, 215, 0), center=True)
        text(self.screen, "Press Q to quit", SW // 2, SH // 2 + 120,
             size=18, color=(200, 200, 200), center=True)


# ---------------------------------------------------------------------------
# Name entry screen
# ---------------------------------------------------------------------------

def name_screen(screen):
    """Simple name entry before the game starts."""
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 28)
    font_small = pygame.font.SysFont("arial", 20)
    names = ["", ""]
    active = 0
    prompts = ["Player 1 name:", "Player 2 name:"]

    while True:
        screen.fill((20, 40, 20))
        text(screen, "DURAK", SW // 2, 80, size=64, bold=True,
             color=(255, 215, 0), center=True)
        text(screen, "Enter player names", SW // 2, 150, size=22,
             color=(200, 200, 200), center=True)

        for i, (prompt, name) in enumerate(zip(prompts, names)):
            y = 230 + i * 90
            text(screen, prompt, SW // 2 - 200, y, size=20,
                 color=(180, 220, 180))
            box = pygame.Rect(SW // 2 - 200, y + 32, 400, 44)
            color = (80, 130, 80) if i == active else (50, 80, 50)
            pygame.draw.rect(screen, color, box, border_radius=8)
            pygame.draw.rect(screen, (200, 200, 200), box, 2, border_radius=8)
            display = name + ("|" if i == active else "")
            s = font.render(display, True, (255, 255, 255))
            screen.blit(s, (box.x + 10, box.y + 8))

        text(screen, "Press Tab to switch field, Enter to start",
             SW // 2, 450, size=18, color=(160, 160, 160), center=True)

        pygame.display.flip()
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_TAB:
                    active = 1 - active
                elif event.key == pygame.K_RETURN:
                    n1 = names[0].strip() or "Player 1"
                    n2 = names[1].strip() or "Player 2"
                    return [n1, n2]
                elif event.key == pygame.K_BACKSPACE:
                    names[active] = names[active][:-1]
                else:
                    if len(names[active]) < 16 and event.unicode.isprintable():
                        names[active] += event.unicode
            if event.type == pygame.MOUSEBUTTONDOWN:
                for i in range(2):
                    box = pygame.Rect(SW // 2 - 200, 230 + i * 90 + 32, 400, 44)
                    if box.collidepoint(event.pos):
                        active = i


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((SW, SH))
    pygame.display.set_caption("Durak")
    clock = pygame.time.Clock()

    names = name_screen(screen)
    game = DurakGame(screen, names)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    pygame.quit(); sys.exit()
                # Quick card selection with number keys
                if not game.privacy and event.unicode.isdigit():
                    idx = int(event.unicode)
                    if idx < len(game.me.hand):
                        game.selected = game.me.hand[idx]
            game.handle_event(event)

        game.draw()
        pygame.display.flip()
        clock.tick(FPS)

if __name__ == "__main__":
    main()
