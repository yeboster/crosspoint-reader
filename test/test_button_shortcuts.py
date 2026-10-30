"""Run with python3 test/test_button_shortcuts.py (requires a host C++ compiler)."""

from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src/MappedInputManager.cpp").read_text()
# Exercise the production side-chord, power-click and edge-query methods.
methods = []
for signature, following in (
    ("void MappedInputManager::update(", "bool MappedInputManager::isNavDirectionSwapped("),
    ("bool MappedInputManager::wasPressed(", "bool MappedInputManager::wasLongPressed("),
    ("bool MappedInputManager::isPressed(", "MappedInputManager::Labels MappedInputManager::mapLabels("),
):
    methods.append(signature + source.split(signature, 1)[1].split(following, 1)[0])

stub = r"""
#pragma once
#include <cstdint>
struct HalGPIO {
  static constexpr uint8_t BTN_BACK = 0, BTN_CONFIRM = 1, BTN_UP = 4, BTN_DOWN = 5, BTN_POWER = 6;
  bool next[7]{}, down[7]{}, prev[7]{};
  unsigned long powerHeld = 100;
  void update() {
    for (int i = 0; i < 7; ++i) {
      prev[i] = down[i];
      down[i] = next[i];
    }
  }
  bool wasPressed(uint8_t b) const { return down[b] && !prev[b]; }
  bool wasReleased(uint8_t b) const { return !down[b] && prev[b]; }
  bool isPressed(uint8_t b) const { return down[b]; }
  bool wasAnyPressed() const {
    for (uint8_t i = 0; i < 7; ++i) if (wasPressed(i)) return true;
    return false;
  }
  bool wasAnyReleased() const {
    for (uint8_t i = 0; i < 7; ++i) if (wasReleased(i)) return true;
    return false;
  }
  unsigned long getHeldTime() const { return 100; }
  unsigned long getPowerButtonHeldTime() const { return powerHeld; }
  bool hasTouch() const { return false; }
  bool wasCapacitivePagePressed() const { return false; }
  bool hasHomeKey() const { return false; }
  bool wasHomeKeyTapped() const { return false; }
  bool wasHomeKeyLongPressed() const { return false; }
  bool wasHomeKeyPressed() const { return false; }
};
"""
harness = r"""
#include <cassert>
#include "MappedInputManager.h"
class GfxRenderer {};
unsigned long nowMs = 1000;
unsigned long millis() { return nowMs; }
constexpr unsigned long TOUCH_HELD_OVERRIDE_WINDOW_MS = 250;
struct CrossPointSettings {
  enum { VIBRATION_OFF, VIBRATION_TOUCH_PAGE };
  enum SHORT_PWRBTN { IGNORE = 0, PWR_CONFIRM = 5, PWR_BOOKMARK = 7, PWR_SYNC = 8, PWR_READER_MENU = 9, PWR_BACK = 10 };
  int shortPwrBtn = IGNORE;
  enum BUTTON_SHORTCUT {
    SHORTCUT_OFF, SHORTCUT_CONFIRM, SHORTCUT_BACK, SHORTCUT_CLIPPING, SHORTCUT_NIGHT_MODE,
    SHORTCUT_REFRESH, SHORTCUT_BOOKMARK, SHORTCUT_READER_MENU, SHORTCUT_DICTIONARY
  };
  int sideChordAction = SHORTCUT_OFF, sideHoldAction = SHORTCUT_OFF, doubleClickPwrAction = SHORTCUT_OFF;
  int vibration = VIBRATION_OFF, hapticIntensity = 0;
  int homeButtonTapAction = 0, homeButtonDoubleTapAction = 0, homeButtonLongPressAction = 0;
  unsigned long getPowerButtonDuration() const { return 400; }
} SETTINGS;
struct HalHaptics {
  static void feedback(bool, bool, int) {}
  static void longPress(bool, int) {}
};
// Button values Back..Power match the stub's physical indexes.
bool MappedInputManager::mapButton(Button b, bool (HalGPIO::*fn)(uint8_t) const) const {
  return readButton(static_cast<uint8_t>(b), fn);
}
bool sideChordBoard = true;
bool MappedInputManager::supportsSideChord() { return sideChordBoard; }
bool MappedInputManager::wasBackGesture() const { return false; }
MappedInputManager::SwipeDir MappedInputManager::wasSwipe(int*, int*) const { return SwipeDir::None; }
""" + "\n".join(methods) + r"""
HalGPIO gpio;
GfxRenderer renderer;
MappedInputManager input(gpio, renderer);
using Button = MappedInputManager::Button;
bool readerArmed = false;

void frame(unsigned long advanceMs) {
  // Stands in for the previous frame's EPUB reader loop.
  if (readerArmed) input.armPowerDoubleClick();
  nowMs += advanceMs;
  input.update();
}
bool clipping() { return input.homeButtonAction() == HomeButtonAction::CreateClipping; }
bool clicked(Button b) { return input.wasPressed(b) && input.wasReleased(b); }
bool quiet(Button b) { return !input.wasPressed(b) && !input.wasReleased(b); }
bool action(HomeButtonAction a) { return input.homeButtonAction() == a; }

void sideChord() {
  // Disabled: a side press passes straight through.
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  assert(input.wasPressed(Button::Up));
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(10);
  assert(input.wasReleased(Button::Up));

  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_CONFIRM;
  // A lone press is held back until the window ends, then replayed once.
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  assert(!input.wasPressed(Button::Up) && input.isPressed(Button::Up));
  frame(50);
  assert(!input.wasPressed(Button::Up));
  frame(50);
  assert(input.wasPressed(Button::Up) && quiet(Button::Confirm));
  frame(10);
  assert(!input.wasPressed(Button::Up));
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(10);
  assert(input.wasReleased(Button::Up));

  // A quick tap gets both edges in its release frame.
  gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  assert(!input.wasPressed(Button::Down));
  gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(30);
  assert(clicked(Button::Down));

  // Second key inside the window: one Confirm, side keys hidden until both are up.
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(40);
  assert(clicked(Button::Confirm) && input.getHeldTime() == 0);
  assert(quiet(Button::Up) && quiet(Button::Down));
  assert(!input.isPressed(Button::Up) && !input.isPressed(Button::Down));
  frame(500);
  assert(quiet(Button::Confirm) && !input.isPressed(Button::Down));
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(10);
  assert(quiet(Button::Up) && quiet(Button::Confirm));
  gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(quiet(Button::Down) && quiet(Button::Confirm));
  frame(10);

  // Both keys in the same frame.
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  assert(clicked(Button::Confirm));
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(quiet(Button::Up) && quiet(Button::Down));
  frame(10);

  // A second key after the window is a normal press, not a chord.
  gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  frame(100);
  assert(input.wasPressed(Button::Down));
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  assert(input.wasPressed(Button::Up) && quiet(Button::Confirm));
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(input.wasReleased(Button::Up) && input.wasReleased(Button::Down));

  // Turning the setting off with the chord keeps the keys hidden until release.
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  assert(clicked(Button::Confirm));
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_OFF;
  frame(600);
  assert(!input.isPressed(Button::Up) && !input.isPressed(Button::Down));
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(quiet(Button::Up) && quiet(Button::Down));
  frame(10);

  // Boards that cannot read both side keys never hold a press back.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_CONFIRM;
  sideChordBoard = false;
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  assert(input.wasPressed(Button::Up));
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(10);
  sideChordBoard = true;

  // The chord can act as Back instead.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_BACK;
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  assert(clicked(Button::Back) && quiet(Button::Confirm) && input.getHeldTime() == 0);
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(quiet(Button::Back) && quiet(Button::Up) && quiet(Button::Down));
  frame(10);

  // Or start a clipping, with neither button reported.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_CLIPPING;
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(10);
  assert(clipping() && quiet(Button::Confirm) && quiet(Button::Back) && quiet(Button::Up));
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(!clipping() && quiet(Button::Down));
  frame(10);
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_OFF;
}

void powerClick(unsigned long heldMs) {
  gpio.powerHeld = heldMs;
  gpio.next[HalGPIO::BTN_POWER] = true;
  frame(10);
  gpio.next[HalGPIO::BTN_POWER] = false;
  frame(heldMs);
}

void powerShortcuts() {
  SETTINGS.shortPwrBtn = CrossPointSettings::PWR_BACK;
  powerClick(100);
  assert(clicked(Button::Back) && input.wasReleased(Button::Power));
  frame(10);
  assert(quiet(Button::Back));
  // A long press is not a short click.
  powerClick(900);
  assert(quiet(Button::Back));
  // A short click can act as Confirm instead.
  SETTINGS.shortPwrBtn = CrossPointSettings::PWR_CONFIRM;
  powerClick(100);
  assert(clicked(Button::Confirm) && quiet(Button::Back));
  SETTINGS.shortPwrBtn = CrossPointSettings::PWR_BACK;

  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_CLIPPING;
  // Outside the EPUB reader a click is never held back.
  powerClick(100);
  assert(clicked(Button::Back) && !clipping());

  readerArmed = true;
  frame(10);
  // Single click: Back only once the double-click window has passed.
  powerClick(100);
  assert(quiet(Button::Back) && !input.wasReleased(Button::Power) && !clipping());
  frame(300);
  assert(quiet(Button::Back));
  frame(150);
  assert(clicked(Button::Back) && input.wasReleased(Button::Power) && input.getHeldTime() == 0);
  frame(10);
  assert(quiet(Button::Back));

  // Double click: clipping action, no Back and no replayed release.
  powerClick(100);
  powerClick(100);
  assert(clipping() && quiet(Button::Back) && !input.wasReleased(Button::Power));
  frame(500);
  assert(!clipping() && quiet(Button::Back) && !input.wasReleased(Button::Power));

  // A second click seen after the window (slow frame) replays the first and
  // starts a new wait.
  powerClick(100);
  frame(290);
  powerClick(100);
  assert(clicked(Button::Back) && !clipping());
  frame(450);
  assert(clicked(Button::Back));

  // No replay while power is held again; a longer second press then releases
  // together with the replayed click.
  powerClick(100);
  gpio.next[HalGPIO::BTN_POWER] = true;
  frame(10);
  frame(500);
  assert(quiet(Button::Back) && !input.wasReleased(Button::Power));
  gpio.powerHeld = 350;
  gpio.next[HalGPIO::BTN_POWER] = false;
  frame(10);
  assert(clicked(Button::Back) && !clipping());
  frame(10);

  // The main loop consuming a release (screenshot, wake) drops the click.
  powerClick(100);
  input.cancelPowerClick();
  frame(500);
  assert(quiet(Button::Back));

  // Leaving the reader drops a held-back click instead of replaying it.
  powerClick(100);
  readerArmed = false;
  frame(10);
  frame(500);
  assert(quiet(Button::Back) && !input.wasReleased(Button::Power));

  // A hold past the click limit passes through at once.
  readerArmed = true;
  SETTINGS.shortPwrBtn = CrossPointSettings::IGNORE;
  frame(10);
  powerClick(350);
  assert(input.wasReleased(Button::Power) && !clipping());

  // Click for Confirm, double click for Back: works on every screen.
  readerArmed = false;
  SETTINGS.shortPwrBtn = CrossPointSettings::PWR_CONFIRM;
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_BACK;
  frame(10);
  powerClick(100);
  assert(quiet(Button::Confirm) && quiet(Button::Back));
  frame(450);
  assert(clicked(Button::Confirm) && quiet(Button::Back));
  frame(10);
  powerClick(100);
  powerClick(100);
  assert(clicked(Button::Back) && quiet(Button::Confirm) && !clipping() && input.getHeldTime() == 0);
  frame(500);
  assert(quiet(Button::Back) && quiet(Button::Confirm));
  // Another key pressed during the wait releases the click first.
  powerClick(100);
  gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(50);
  assert(clicked(Button::Confirm) && input.wasPressed(Button::Down));
  gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  frame(500);
  assert(quiet(Button::Confirm) && quiet(Button::Back));
  // With the side chord on, the side press is held back, so Confirm leads.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_CLIPPING;
  powerClick(100);
  gpio.next[HalGPIO::BTN_DOWN] = true;
  frame(50);
  assert(clicked(Button::Confirm) && !input.wasPressed(Button::Down));
  frame(100);
  assert(input.wasPressed(Button::Down) && quiet(Button::Confirm));
  gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  frame(500);
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_OFF;
  // The swapped mapping.
  SETTINGS.shortPwrBtn = CrossPointSettings::PWR_BACK;
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_CONFIRM;
  powerClick(100);
  powerClick(100);
  assert(clicked(Button::Confirm) && quiet(Button::Back));
  frame(500);
  assert(quiet(Button::Back) && quiet(Button::Confirm));

  // Reader actions wait for the reader to arm them; the others act anywhere.
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_BOOKMARK;
  powerClick(100);
  assert(clicked(Button::Back));
  powerClick(100);
  assert(clicked(Button::Back) && !action(HomeButtonAction::Bookmark));
  frame(500);
  readerArmed = true;
  frame(10);
  powerClick(100);
  powerClick(100);
  assert(action(HomeButtonAction::Bookmark) && quiet(Button::Back));
  frame(500);
  readerArmed = false;
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_REFRESH;
  powerClick(100);
  powerClick(100);
  assert(action(HomeButtonAction::Refresh) && quiet(Button::Back));
  frame(500);
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_NIGHT_MODE;
  powerClick(100);
  powerClick(100);
  assert(input.wasNightModeShortcut() && action(HomeButtonAction::Ignore) && quiet(Button::Back));
  frame(10);
  assert(!input.wasNightModeShortcut());
  frame(500);
  SETTINGS.doubleClickPwrAction = CrossPointSettings::SHORTCUT_OFF;
  SETTINGS.shortPwrBtn = CrossPointSettings::IGNORE;
}

void pressSides(bool held) {
  gpio.next[HalGPIO::BTN_UP] = gpio.next[HalGPIO::BTN_DOWN] = held;
  frame(10);
}

void sideHold() {
  // Hold set: a short chord acts on release, a long one runs the hold action.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_CONFIRM;
  SETTINGS.sideHoldAction = CrossPointSettings::SHORTCUT_NIGHT_MODE;
  pressSides(true);
  assert(quiet(Button::Confirm) && quiet(Button::Up) && quiet(Button::Down));
  frame(200);
  assert(quiet(Button::Confirm) && !input.wasNightModeShortcut());
  pressSides(false);
  assert(clicked(Button::Confirm) && quiet(Button::Up) && quiet(Button::Down) && input.getHeldTime() == 0);
  frame(10);
  assert(quiet(Button::Confirm));

  pressSides(true);
  frame(699);
  assert(!input.wasNightModeShortcut());
  frame(1);
  assert(input.wasNightModeShortcut() && quiet(Button::Confirm));
  frame(500);
  assert(!input.wasNightModeShortcut() && quiet(Button::Up));
  pressSides(false);
  assert(quiet(Button::Confirm) && quiet(Button::Up) && quiet(Button::Down) && !input.wasNightModeShortcut());
  frame(10);

  // Releasing one key first still counts as a short chord.
  pressSides(true);
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(100);
  assert(clicked(Button::Confirm) && quiet(Button::Up));
  frame(800);
  assert(quiet(Button::Confirm) && !input.wasNightModeShortcut() && quiet(Button::Down));
  gpio.next[HalGPIO::BTN_DOWN] = false;
  frame(10);
  assert(quiet(Button::Down));
  frame(10);

  // Hold only: the short chord does nothing, the hold maps to a reader action.
  SETTINGS.sideChordAction = CrossPointSettings::SHORTCUT_OFF;
  SETTINGS.sideHoldAction = CrossPointSettings::SHORTCUT_READER_MENU;
  pressSides(true);
  pressSides(false);
  assert(quiet(Button::Confirm) && action(HomeButtonAction::Ignore) && quiet(Button::Up));
  frame(10);
  pressSides(true);
  frame(700);
  assert(action(HomeButtonAction::ReaderMenu));
  pressSides(false);
  frame(10);
  // A lone side press is still held back for the chord window.
  gpio.next[HalGPIO::BTN_UP] = true;
  frame(10);
  assert(!input.wasPressed(Button::Up));
  frame(100);
  assert(input.wasPressed(Button::Up));
  gpio.next[HalGPIO::BTN_UP] = false;
  frame(10);
  SETTINGS.sideHoldAction = CrossPointSettings::SHORTCUT_OFF;
}

int main() {
  input.update();
  sideChord();
  powerShortcuts();
  sideHold();
}
"""
with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    (directory / "HalGPIO.h").write_text(stub)
    cpp = directory / "button_shortcuts.cpp"
    executable = directory / "button_shortcuts"
    cpp.write_text("#include <initializer_list>\n" + harness)
    subprocess.run([
        "c++", "-std=c++20", "-DFREEINK_CAP_TOUCH=0", "-I", str(directory),
        "-I", str(ROOT / "src"), str(cpp), "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
print("Button shortcut regression checks passed")
