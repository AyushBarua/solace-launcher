/**
 * Solace Web Controller -- injected into every HTML game via QWebEngineScript.
 */
(function () {
    "use strict";

    var DEFAULT_KEY_MAP = {
        up:     { key: "ArrowUp",    code: "ArrowUp",    keyCode: 38 },
        down:   { key: "ArrowDown",  code: "ArrowDown",  keyCode: 40 },
        left:   { key: "ArrowLeft",  code: "ArrowLeft",  keyCode: 37 },
        right:  { key: "ArrowRight", code: "ArrowRight", keyCode: 39 },
        action: { key: " ",          code: "Space",      keyCode: 32 }
    };

    function getKeyMap() {
        var cfg = (window.__solaceGameConfig && window.__solaceGameConfig.key_map) || {};
        var map = {};
        Object.keys(DEFAULT_KEY_MAP).forEach(function (dir) {
            if (cfg[dir]) {
                var k = cfg[dir];
                map[dir] = { key: k, code: k, keyCode: k.charCodeAt(0) };
            } else {
                map[dir] = DEFAULT_KEY_MAP[dir];
            }
        });
        return map;
    }

    var _heldKeys = {};

    function dispatchKey(keyInfo, type) {
        var target = document.activeElement && document.activeElement !== document.body
            ? document.activeElement
            : document.body;
        var ev = new KeyboardEvent(type, {
            key: keyInfo.key, code: keyInfo.code,
            keyCode: keyInfo.keyCode, which: keyInfo.keyCode,
            bubbles: true, cancelable: true
        });
        target.dispatchEvent(ev);
        if (target !== document) {
            document.dispatchEvent(new KeyboardEvent(type, {
                key: keyInfo.key, code: keyInfo.code,
                keyCode: keyInfo.keyCode, which: keyInfo.keyCode,
                bubbles: true, cancelable: true
            }));
        }
    }

    function handleDirection(dir) {
        var keyMap  = getKeyMap();
        var keyInfo = keyMap[dir];
        if (!keyInfo) return;
        var keyId = keyInfo.key;
        if (!_heldKeys[keyId]) {
            _heldKeys[keyId] = true;
            dispatchKey(keyInfo, "keydown");
        }
        clearTimeout(_heldKeys[keyId + "__timer"]);
        _heldKeys[keyId + "__timer"] = setTimeout(function () {
            if (_heldKeys[keyId]) {
                dispatchKey(keyInfo, "keyup");
                delete _heldKeys[keyId];
            }
        }, 120);
    }

    // ── Continuous axes → held keys (real gameplay input) ────────────────────
    // Hysteresis: press past 0.35, release under 0.22 — no flutter at the edge.
    var PRESS = 0.35, RELEASE = 0.22;
    var _axisHeld = { left: false, right: false, up: false, down: false };

    function axisKey(dir, active) {
        var keyInfo = getKeyMap()[dir];
        if (!keyInfo) return;
        if (active && !_axisHeld[dir]) {
            _axisHeld[dir] = true;
            dispatchKey(keyInfo, "keydown");
        } else if (!active && _axisHeld[dir]) {
            _axisHeld[dir] = false;
            dispatchKey(keyInfo, "keyup");
        }
    }

    function handleAxes(x, y) {
        // Discrete arrow keys for most games…
        axisKey("left",  x < -PRESS || (_axisHeld.left  && x < -RELEASE));
        axisKey("right", x >  PRESS || (_axisHeld.right && x >  RELEASE));
        axisKey("up",    y < -PRESS || (_axisHeld.up    && y < -RELEASE));
        axisKey("down",  y >  PRESS || (_axisHeld.down  && y >  RELEASE));
        // …and the raw continuous axes for games that want ANALOG tilt/gyro
        // (e.g. the tilting maze). x = pron/sup, y = flex/ext, range ~[-1,1].
        window.__solaceAxes = { x: x, y: y };
        window.dispatchEvent(new CustomEvent("solace-axes", { detail: { x: x, y: y } }));
    }

    var _bridge = null;

    // Quit = ESC key (no mouse target to hunt for). A passive hint is shown
    // in the corner; it never intercepts clicks or game input.
    function buildQuitHint() {
        if (document.getElementById("__solace_quit_hint")) return;
        var hint = document.createElement("div");
        hint.id = "__solace_quit_hint";
        hint.innerText = "Press  ESC  to quit";
        hint.style.cssText = [
            "position:fixed", "top:10px", "right:10px",
            "background:rgba(0,0,0,0.55)", "color:#dddddd",
            "padding:6px 14px", "border-radius:8px",
            "font-family:sans-serif", "font-size:13px",
            "z-index:2147483647", "pointer-events:none",
            "user-select:none", "letter-spacing:0.5px"
        ].join(";");
        function attach() { document.body.appendChild(hint); }
        if (document.body) { attach(); }
        else { document.addEventListener("DOMContentLoaded", attach); }
    }

    // ESC anywhere in the page quits the game (capture phase so games can't
    // swallow it).
    window.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && ev.isTrusted) {
            if (_bridge) { _bridge.quit_game(); }
        }
    }, true);

    var _origPrompt = window.prompt;
    window.prompt = function (msg, defaultVal) {
        if (window.__solacePlayerName) { return window.__solacePlayerName; }
        return _origPrompt ? _origPrompt.call(window, msg, defaultVal) : (defaultVal || "Player");
    };

    buildQuitHint();

    function setupChannel() {
        if (typeof qt === "undefined" || !qt.webChannelTransport) {
            setTimeout(setupChannel, 50);
            return;
        }
        new QWebChannel(qt.webChannelTransport, function (channel) {
            _bridge = channel.objects.bridge;
            _bridge.direction_signal.connect(function (dir) {
                handleDirection(dir);
            });
            if (_bridge.axes_signal) {
                _bridge.axes_signal.connect(handleAxes);
            }
            console.log("[Solace] Web controller ready (axes streaming).");
        });
    }

    setupChannel();

}());
