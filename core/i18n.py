"""
core/i18n.py — Lightweight bilingual translation engine for Solace.

Usage:
    from core.i18n import t, set_language, get_language, i18n

    t("welcome_title")          # → "Welcome!" or "स्वागत है!"
    set_language("hi")          # switches to Hindi
    i18n.language_changed.emit  # signal for UI refresh

Supported languages: "en" (English), "hi" (Hindi)
"""
import os
import json
from PyQt6.QtCore import QObject, pyqtSignal


# ── Translation dictionary ────────────────────────────────────────────────────
_STRINGS: dict[str, dict[str, str]] = {

    # ── Language picker ────────────────────────────────────────────────────────
    "lang_step_title":    {"en": "Choose Your Language",      "hi": "अपनी भाषा चुनें"},
    "lang_step_subtitle": {"en": "You can change this later in Settings",
                           "hi": "आप इसे बाद में सेटिंग्स में बदल सकते हैं"},
    "lang_continue":      {"en": "Continue →",                "hi": "जारी रखें →"},

    # ── Login / sign-up ────────────────────────────────────────────────────────
    "login_welcome":      {"en": "Welcome back",              "hi": "वापसी पर स्वागत है"},
    "login_subtitle":     {"en": "Please enter your details", "hi": "कृपया अपना विवरण दर्ज करें"},
    "login_email":        {"en": "Email address",             "hi": "ईमेल पता"},
    "login_password":     {"en": "Password",                  "hi": "पासवर्ड"},
    "login_keep":         {"en": "Keep me signed in",         "hi": "मुझे साइन इन रखें"},
    "login_forgot":       {"en": "Forgot password?",          "hi": "पासवर्ड भूल गए?"},
    "login_signin":       {"en": "Sign in",                   "hi": "साइन इन करें"},
    "login_or":           {"en": "or",                        "hi": "या"},
    "login_google":       {"en": "Sign in with Google",       "hi": "Google से साइन इन करें"},
    "login_no_account":   {"en": "Don't have an account?",    "hi": "खाता नहीं है?"},
    "login_signup":       {"en": "Sign up",                   "hi": "साइन अप करें"},
    "reg_title":          {"en": "Create Account",            "hi": "खाता बनाएँ"},
    "reg_subtitle":       {"en": "Fill in your details to get started",
                           "hi": "शुरू करने के लिए अपना विवरण भरें"},
    "reg_name":           {"en": "Full Name",                 "hi": "पूरा नाम"},
    "reg_name_ph":        {"en": "Jane Doe",                  "hi": "आपका नाम"},
    "reg_pass_ph":        {"en": "Minimum 6 characters",      "hi": "कम से कम 6 अक्षर"},
    "reg_button":         {"en": "Create account",            "hi": "खाता बनाएँ"},
    "reg_have_account":   {"en": "Already have an account?",  "hi": "पहले से खाता है?"},

    # ── Progress page ─────────────────────────────────────────────────────────
    "prog_title":         {"en": "Your Progress",             "hi": "आपकी प्रगति"},
    "prog_total":         {"en": "Total Sessions",            "hi": "कुल सत्र"},
    "prog_streak":        {"en": "Day Streak",                "hi": "दिनों की श्रृंखला"},
    "prog_today":         {"en": "Played Today",              "hi": "आज खेला"},
    "prog_rom_imp":       {"en": "ROM Improvement",           "hi": "गति सुधार"},
    "prog_movement":      {"en": "Your Movement",             "hi": "आपकी गति"},
    "prog_activity":      {"en": "Activity",                  "hi": "गतिविधि"},
    "prog_milestones":    {"en": "Milestones",                "hi": "उपलब्धियाँ"},
    "prog_report":        {"en": "Doctor's Report",           "hi": "डॉक्टर की रिपोर्ट"},
    "prog_rom_empty":     {"en": "Your wrist range-of-motion will appear here.\n"
                                 "Complete the daily warmup before playing to start tracking.",
                           "hi": "आपकी कलाई की गति सीमा यहाँ दिखेगी।\n"
                                 "ट्रैकिंग शुरू करने के लिए खेलने से पहले दैनिक वार्मअप पूरा करें।"},
    "prog_report_desc":   {"en": "Generate a PDF report your therapist or doctor can download and review. "
                                 "It includes your movement data, session history, pain log, and milestones.",
                           "hi": "एक PDF रिपोर्ट बनाएँ जिसे आपकी थेरेपिस्ट या डॉक्टर देख सकें। "
                                 "इसमें आपकी गति का डेटा, सत्र इतिहास, दर्द लॉग और उपलब्धियाँ शामिल हैं।"},
    "prog_download":      {"en": "  Download PDF",            "hi": "  PDF डाउनलोड करें"},
    "prog_generating":    {"en": "  Generating…",             "hi": "  बना रहे हैं…"},
    "prog_building":      {"en": "Building your report, please wait…",
                           "hi": "आपकी रिपोर्ट बन रही है, कृपया प्रतीक्षा करें…"},

    # ── Movement prompts (warmup + assessment) ────────────────────────────────
    "mp_flexion_main":    {"en": "Twist the handle to the LEFT",  "hi": "हैंडल को बाएँ घुमाएँ"},
    "mp_extension_main":  {"en": "Twist the handle to the RIGHT", "hi": "हैंडल को दाएँ घुमाएँ"},
    "mp_pronation_main":  {"en": "Tilt the wheel to the RIGHT",   "hi": "पहिये को दाएँ झुकाएँ"},
    "mp_supination_main": {"en": "Tilt the wheel to the LEFT",    "hi": "पहिये को बाएँ झुकाएँ"},
    "mp_neutral_main":    {"en": "Hold the controller still",     "hi": "कंट्रोलर को स्थिर रखें"},
    "mp_flexion_hint":    {"en": "like turning a key",            "hi": "जैसे चाबी घुमाते हैं"},
    "mp_extension_hint":  {"en": "like turning the key back",     "hi": "जैसे चाबी वापस घुमाते हैं"},
    "mp_pronation_hint":  {"en": "lean it sideways",              "hi": "इसे बगल में झुकाएँ"},
    "mp_supination_hint": {"en": "lean it sideways",              "hi": "इसे बगल में झुकाएँ"},
    "mp_neutral_hint":    {"en": "in the resting position",       "hi": "आराम की स्थिति में"},

    # ── Assessment wizard ─────────────────────────────────────────────────────
    "aw_hand_title":   {"en": "Which hand will you use?",
                        "hi": "आप कौन सा हाथ इस्तेमाल करेंगे?"},
    "aw_hand_sub":     {"en": "The assessment measures this hand's movement.",
                        "hi": "यह आकलन इसी हाथ की गति मापेगा।"},
    "aw_left_hand":    {"en": "Left hand",   "hi": "बायाँ हाथ"},
    "aw_right_hand":   {"en": "Right hand",  "hi": "दायाँ हाथ"},
    "aw_neutral_title": {"en": "Hold still in the resting position",
                         "hi": "आराम की स्थिति में स्थिर रहें"},
    "aw_neutral_sub":  {"en": "Grip the controller comfortably and don't move…",
                        "hi": "कंट्रोलर को आराम से पकड़ें और हिलाएँ नहीं…"},
    "aw_capture_sub":  {"en": "Watch the model show the movement, then copy it — "
                              "as far as comfortable. Attempt {n} of {t}.",
                        "hi": "पहले मॉडल को गति दिखाते देखें, फिर उसे दोहराएँ — "
                              "जितना आरामदायक हो। प्रयास {n} / {t}।"},
    "aw_rest_title":   {"en": "Relax back to neutral",  "hi": "वापस आराम की स्थिति में आएँ"},
    "aw_rest_sub":     {"en": "Take a breath…",         "hi": "एक साँस लें…"},
    "aw_squeeze_title": {"en": "Squeeze the grip as hard\nas is comfortable",
                         "hi": "जितना आरामदायक हो उतना\nज़ोर से ग्रिप दबाएँ"},
    "aw_summary_title": {"en": "Your baseline",         "hi": "आपकी बेसलाइन"},
    "aw_skip":         {"en": "Skip for now",           "hi": "अभी छोड़ें"},
    "aw_save":         {"en": "Save my baseline",       "hi": "मेरी बेसलाइन सहेजें"},

    # ── Onboarding ─────────────────────────────────────────────────────────────
    "onboarding_step_label":   {"en": "Step {cur} of {tot}",  "hi": "चरण {cur} / {tot}"},
    "onboarding_header":       {"en": "Solace Setup",         "hi": "Solace सेटअप"},
    "welcome_title":           {"en": "Welcome, {name}!",     "hi": "स्वागत है, {name}!"},
    "welcome_body":            {
        "en": "Solace uses fun games to help you regain movement in your\n"
              "arm and hand. Your progress is tracked so your therapist\n"
              "can see how you're improving week by week.",
        "hi": "Solace मज़ेदार खेलों का उपयोग करके आपके हाथ और बाँह की\n"
              "गति वापस पाने में मदद करता है। आपकी थेरेपिस्ट\n"
              "हर हफ़्ते आपकी प्रगति देख सकती हैं।",
    },
    "welcome_btn":             {"en": "  Let's get started  →", "hi": "  शुरू करें  →"},

    # Device step
    "device_title":            {"en": "Connect Your Device",  "hi": "अपना डिवाइस जोड़ें"},
    "device_body":             {
        "en": "Plug in your Solace controller or any hand controller.\n"
              "We'll detect it automatically.",
        "hi": "अपना Solace कंट्रोलर या कोई भी हाथ का कंट्रोलर लगाएं।\n"
              "हम इसे अपने आप पहचान लेंगे।",
    },
    "device_skip":             {"en": "Skip for now",         "hi": "अभी छोड़ें"},
    "device_detected":         {"en": "{name} connected!", "hi": "{name} जुड़ गया!"},
    "device_waiting":          {"en": "Waiting for device…",  "hi": "डिवाइस की प्रतीक्षा…"},

    # Calibration step
    "cal_title":               {"en": "Baseline Calibration", "hi": "बेसलाइन कैलिब्रेशन"},
    "cal_body":                {
        "en": "Move your arm or wrist as far as you comfortably can\n"
              "in each direction. This sets your starting range of motion.",
        "hi": "अपना हाथ या कलाई जितना आरामदायक हो उतना हर\n"
              "दिशा में हिलाएँ। यह आपकी गति की सीमा तय करता है।",
    },
    "cal_done":                {"en": "Done! Great work.",   "hi": "बहुत अच्छे!"},
    "cal_skip":                {"en": "Skip calibration",      "hi": "कैलिब्रेशन छोड़ें"},

    # ── Bottom nav ─────────────────────────────────────────────────────────────
    "nav_play":                {"en": "Play",                  "hi": "खेलें"},
    "play_row_featured":       {"en": "Featured",             "hi": "विशेष"},
    "play_row_mine":          {"en": "Your other games",      "hi": "आपके अन्य गेम"},
    "play_row_more":           {"en": "Get more games",        "hi": "और गेम पाएं"},
    "play_row_pc":             {"en": "On this computer",      "hi": "इस कंप्यूटर पर"},
    "play_btn_play":           {"en": "Play",                  "hi": "खेलें"},
    "play_btn_download":       {"en": "Download",              "hi": "डाउनलोड करें"},
    "play_btn_downloading":    {"en": "Downloading…",          "hi": "डाउनलोड हो रहा है…"},
    "play_btn_retry":          {"en": "Retry download",        "hi": "फिर से डाउनलोड करें"},
    "play_btn_soon":           {"en": "Coming soon",           "hi": "जल्द आ रहा है"},
    "play_tag_rec":            {"en": "RECOMMENDED TODAY",     "hi": "आज के लिए सुझाव"},
    "play_tag_download":       {"en": "READY TO DOWNLOAD",     "hi": "डाउनलोड के लिए तैयार"},
    "play_tag_soon":           {"en": "COMING SOON",           "hi": "जल्द आ रहा है"},
    "nav_home":                {"en": "Home",                  "hi": "होम"},
    "nav_library":             {"en": "Library",               "hi": "लाइब्रेरी"},
    "nav_progress":            {"en": "Progress",              "hi": "प्रगति"},
    "nav_reports":             {"en": "Reports",               "hi": "रिपोर्ट"},
    "nav_settings":            {"en": "Settings",              "hi": "सेटिंग्स"},

    # ── Pain check-in ──────────────────────────────────────────────────────────
    "pain_title":              {"en": "How did that feel, {name}?",
                                "hi": "{name}, कैसा लगा?"},
    "pain_subtitle":           {
        "en": "Tap the button that best describes how you're feeling right now.",
        "hi": "वह बटन दबाएं जो अभी आपकी भावना को सबसे अच्छी तरह बताता हो।",
    },
    "pain_good":               {"en": "Great!",                "hi": "बढ़िया!"},
    "pain_tired":              {"en": "A bit tired",           "hi": "थोड़ी थकान"},
    "pain_pain":               {"en": "Some pain",             "hi": "कुछ दर्द"},
    "pain_countdown":          {
        "en": "Continuing with 'Tired' in {sec}s — tap a button to choose",
        "hi": "{sec} सेकंड में 'थकान' के साथ जारी — बटन दबाकर चुनें",
    },
    "pain_msg_good":           {"en": "Great session! See you tomorrow.",
                                "hi": "बेहतरीन सत्र! कल मिलते हैं।"},
    "pain_msg_tired":          {"en": "Rest well — recovery is part of the journey.",
                                "hi": "अच्छे से आराम करें — रिकवरी यात्रा का हिस्सा है।"},
    "pain_msg_pain":           {
        "en": "We'll go a little easier next time.\nYour therapist will see this in your next report.",
        "hi": "अगली बार थोड़ा आसान रखेंगे।\nआपकी थेरेपिस्ट अगली रिपोर्ट में यह देखेंगी।",
    },

    # ── Settings page ──────────────────────────────────────────────────────────
    "settings_title":          {"en": "Settings",              "hi": "सेटिंग्स"},
    "settings_desc":           {
        "en": "Adjust interface and accessibility options to fit your needs.",
        "hi": "अपनी ज़रूरत के अनुसार इंटरफ़ेस और सुलभता विकल्प बदलें।",
    },
    "settings_lang_panel":     {"en": "Language / भाषा",      "hi": "भाषा / Language"},
    "settings_lang_desc":      {
        "en": "Choose the interface language.",
        "hi": "इंटरफ़ेस की भाषा चुनें।",
    },

    # ── Home page ──────────────────────────────────────────────────────────────
    "home_title":              {"en": "Today's Journey",        "hi": "आज की यात्रा"},
    "home_subtitle":           {"en": "Pick up where you left off.",
                                "hi": "जहाँ छोड़ा था, वहीं से शुरू करें।"},
    "home_streak":             {"en": "{n} day streak",         "hi": "{n} दिन की लकीर"},

    # ── Library / Game descriptions (shown on game cards) ─────────────────────
    "game_desc_snake_game": {
        "en": "Control a growing snake across the board — trains smooth arm sweeping and direction changes.",
        "hi": "बढ़ते सांप को बोर्ड पर चलाएं — हाथ की लहरदार गति और दिशा बदलने का अभ्यास।",
    },
    "game_desc_javascript_racer_v5": {
        "en": "Race down a 3D road by steering left and right — fast reflexes, great visual reward.",
        "hi": "3D सड़क पर दौड़ें, बाएं-दाएं स्टीयर करें — तेज़ प्रतिक्रिया, शानदार दृश्य अनुभव।",
    },
    "game_desc_archery_game_hassanhaseen": {
        "en": "Pull back and release to fire arrows — a satisfying tension-and-release motion.",
        "hi": "खींचें और छोड़ें तीर चलाने के लिए — संतोषजनक तनाव-और-छोड़ने की गति।",
    },
    "game_desc_tilting_maze_game": {
        "en": "Tilt the board to guide a ball to the goal — trains fine rotation control.",
        "hi": "गेंद को लक्ष्य तक पहुंचाने के लिए बोर्ड झुकाएं — सूक्ष्म घुमाव नियंत्रण का अभ्यास।",
    },
    "game_desc_archery_game_svg": {
        "en": "Aim and shoot with a curved-arc arrow — trains fluid aiming and smooth release.",
        "hi": "घुमावदार तीर से निशाना लगाएं — सहज निशानेबाजी और स्मूद रिलीज़ का अभ्यास।",
    },
    "game_desc_simon_says": {
        "en": "Watch the pattern, then repeat it — sharpens memory and finger coordination.",
        "hi": "पैटर्न देखें, फिर दोहराएं — स्मृति और उंगली समन्वय को तेज़ करता है।",
    },
    "game_desc_classic_pong_game": {
        "en": "Bounce a ball back and forth — great for building quick arm reactions.",
        "hi": "गेंद को आगे-पीछे उछालें — तेज़ हाथ प्रतिक्रिया बनाने के लिए बढ़िया।",
    },
    "game_desc_bubble_shooter_html5": {
        "en": "Aim and pop clusters of bubbles — calm, satisfying wrist control.",
        "hi": "बुलबुलों के समूह पर निशाना लगाएं और तोड़ें — शांत, संतोषजनक कलाई नियंत्रण।",
    },
    "game_desc_arkanoid": {
        "en": "Move a paddle to smash through bricks — perfect for wide, sweeping arm movement.",
        "hi": "पैडल चलाकर ईंटें तोड़ें — चौड़ी, लहरदार हाथ गति के लिए एकदम सही।",
    },
    "game_desc_fruit_game": {
        "en": "Catch falling fruit and dodge bombs — quick left-right arm reactions.",
        "hi": "गिरते फल पकड़ें और बम से बचें — तेज़ बाएं-दाएं हाथ प्रतिक्रिया।",
    },
    "game_desc_fishing_game": {
        "en": "Cast your line and reel in fish — relaxed, flowing arm movement.",
        "hi": "लाइन डालें और मछली खींचें — आरामदायक, प्रवाहमान हाथ की गति।",
    },

    # Coming-soon games
    "game_desc_balloon_pop": {
        "en": "Pop balloons to train large arm movement and tracking.",
        "hi": "गुब्बारे फोड़ें, बाँह की बड़ी गतिविधि और ट्रैकिंग का अभ्यास करें।",
    },
    "game_desc_fruit_ninja": {
        "en": "Slice fruit flying across the screen — trains speed and tracking.",
        "hi": "स्क्रीन पर उड़ते फलों को काटें — गति और ट्रैकिंग का अभ्यास।",
    },
    "game_desc_stroky_painter": {
        "en": "Paint strokes on canvas using the Solace controller — ideal for fine motor recovery.",
        "hi": "Solace कंट्रोलर से कैनवास पर रंग भरें — महीन मोटर रिकवरी के लिए आदर्श।",
    },
    "game_desc_maze_navigator": {
        "en": "Guide a ball through a maze — trains precise fine motor control.",
        "hi": "भूलभुलैया में गेंद को मार्गदर्शित करें — सटीक महीन मोटर नियंत्रण का अभ्यास।",
    },

    # ── Progress page chart explanations ──────────────────────────────────────
    "progress_title":            {"en": "Your Progress",       "hi": "आपकी प्रगति"},
    "progress_sessions_label":   {"en": "SESSIONS",             "hi": "सत्र"},
    "progress_streak_label":     {"en": "DAY STREAK",           "hi": "लगातार दिन"},
    "progress_minutes_label":    {"en": "MINUTES",              "hi": "मिनट"},
    "progress_rom_label":        {"en": "ROM SCORE",            "hi": "ROM स्कोर"},
    "progress_weekly_chart_title": {"en": "Weekly Activity",   "hi": "साप्ताहिक गतिविधि"},
    "progress_weekly_chart_hint": {
        "en": "Minutes of therapy per day this week",
        "hi": "इस सफ़्ताह प्रति दिन थेरेपी के मिनट",
    },
    "progress_rom_chart_title":  {"en": "Range of Motion",     "hi": "गति की सीमा"},
    "progress_rom_chart_hint":   {
        "en": "How far you can move compared to your baseline",
        "hi": "बेसलाइन की तुलना में आप कितना हिल सकते हैं",
    },
    "progress_milestones_title": {"en": "Milestones",          "hi": "उपलब्धियाँ"},
    "progress_no_data":          {
        "en": "No sessions recorded yet.\nPlay a game to see your progress here!",
        "hi": "अभी कोई सत्र दर्ज नहीं।\nप्रगति देखने के लिए खेल खेलें!",
    },
    "progress_export_btn":       {"en": "Export Report",       "hi": "रिपोर्ट निर्यात करें"},
    "progress_generating":       {"en": "Generating…",         "hi": "तैयार हो रहा है…"},

    # ── Common ─────────────────────────────────────────────────────────────────
    "btn_continue":              {"en": "Continue",            "hi": "जारी रखें"},
    "btn_skip":                  {"en": "Skip",                "hi": "छोड़ें"},
    "btn_save":                  {"en": "Save",                "hi": "सहेजें"},
    "btn_cancel":                {"en": "Cancel",              "hi": "रद्द करें"},
    "btn_back":                  {"en": "Back",                "hi": "वापस"},
    "btn_done":                  {"en": "Done",                "hi": "हो गया"},
    "btn_play_now":              {"en": "Play Now",         "hi": "अभी खेलें"},
    "btn_download":              {"en": "Download",         "hi": "डाउनलोड"},
    "btn_coming_soon":           {"en": "Coming Soon",         "hi": "जल्द आ रहा है"},
    "btn_downloading":           {"en": "Downloading…",    "hi": "डाउनलोड हो रहा है…"},
}


# ── Signal hub ────────────────────────────────────────────────────────────────

class _I18nHub(QObject):
    language_changed = pyqtSignal(str)   # emits the new lang code "en"/"hi"

i18n = _I18nHub()
_current_lang: str = "en"


# ── Public API ────────────────────────────────────────────────────────────────

def get_language() -> str:
    """Return the active language code ("en" or "hi")."""
    return _current_lang


def set_language(code: str, save: bool = True) -> None:
    """Switch to the given language code and emit language_changed."""
    global _current_lang
    code = code.lower().strip()
    if code not in ("en", "hi"):
        code = "en"
    _current_lang = code
    if save:
        _save_language(code)
    i18n.language_changed.emit(code)


def t(key: str, **kwargs) -> str:
    """
    Return the translated string for *key* in the active language.
    Extra kwargs are passed to str.format() on the result.

    Example:
        t("welcome_title", name="Priya")  → "स्वागत है, Priya!"
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key   # graceful fallback: return the key itself
    text = entry.get(_current_lang) or entry.get("en") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


def get_game_desc(game_id: str, fallback_en: str = "") -> str:
    """
    Return the translated description for a game ID.
    Falls back to fallback_en if no Hindi translation exists.
    """
    key = f"game_desc_{game_id}"
    entry = _STRINGS.get(key)
    if entry is None:
        return fallback_en
    return entry.get(_current_lang) or entry.get("en") or fallback_en


# ── Persistence ───────────────────────────────────────────────────────────────

def _settings_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "global_settings.json")


def _save_language(code: str) -> None:
    path = _settings_path()
    try:
        existing: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
        existing["language"] = code
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def load_saved_language() -> str:
    """Read the persisted language from global_settings.json."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("language", "en")
    except Exception:
        return "en"


def has_chosen_language() -> bool:
    """True only when the user has explicitly selected a language before."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return "language" in json.load(f)
    except Exception:
        return False


def init() -> None:
    """
    Call once at app start (in launcher.py) to restore the saved language
    without emitting language_changed (avoids premature UI refresh).
    """
    global _current_lang
    _current_lang = load_saved_language()
