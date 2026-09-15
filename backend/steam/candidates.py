"""Candidate game -> dedicated-server appid pairs.

Every pair here is UNVERIFIED input to build_catalog.py, which checks each one
against live Steam appinfo and drops anything that does not resolve to a real
server app for that game. Never treat this file as authoritative on its own.
"""

# game_appid: (game name hint, dedicated server appid or None if server ships with the game)
CANDIDATES = {
    # --- Valve / Source ---
    10: ("Counter-Strike", 90), 20: ("Team Fortress Classic", 90),
    30: ("Day of Defeat", 90), 40: ("Deathmatch Classic", 90),
    50: ("Half-Life: Opposing Force", 90), 70: ("Half-Life", 90),
    240: ("Counter-Strike: Source", 232330), 300: ("Day of Defeat: Source", 232290),
    320: ("Half-Life 2: Deathmatch", 232370), 360: ("Half-Life Deathmatch: Source", 255470),
    440: ("Team Fortress 2", 232250), 500: ("Left 4 Dead", 222840),
    550: ("Left 4 Dead 2", 222860), 630: ("Alien Swarm", 635),
    730: ("Counter-Strike 2", 740), 4000: ("Garry's Mod", 4020),
    17520: ("Synergy", 17525), 224260: ("No More Room in Hell", 317670),

    # --- Survival / sandbox ---
    252490: ("Rust", 258550), 892970: ("Valheim", 896660),
    346110: ("ARK: Survival Evolved", 376030), 2399830: ("ARK: Survival Ascended", 2430930),
    1623730: ("Palworld", 2394010), 108600: ("Project Zomboid", 380870),
    251570: ("7 Days to Die", 294420), 526870: ("Satisfactory", 1690800),
    1604030: ("V Rising", 1829350), 322330: ("Don't Starve Together", 343050),
    244850: ("Space Engineers", 298740), 1963720: ("Core Keeper", 1963720),
    1203620: ("Enshrouded", 2278520), 304930: ("Unturned", 1110390),
    242760: ("The Forest", 556450), 1326470: ("Sons of the Forest", 2465200),
    440900: ("Conan Exiles", 443030), 834910: ("ATLAS", 1006030),
    361420: ("ASTRONEER", 728470), 382310: ("Eco", 739590),
    333950: ("Medieval Engineers", 367970), 211820: ("Starbound", 533830),
    544550: ("Stationeers", 600760), 376210: ("The Isle", 412680),
    393420: ("Hurtworld", 405100), 299740: ("Miscreated", 302200), 366220: ("Wurm Unlimited", 402370),
    602960: ("Barotrauma", 1026340),
    513710: ("SCUM", 3792580), 445220: ("Avorion", 565060),
    383120: ("Empyrion - Galactic Survival", 530870), 1149460: ("ICARUS", 2089300),
    427410: ("Abiotic Factor", 2857200), 899770: ("Last Oasis", 920720), 2646460: ("Soulmask", 3017300),
    427520: ("Factorio", None), 105600: ("Terraria", None),
    1966010: ("Necesse", None), 2379780: ("Vintage Story", None),

    # --- Military / shooters ---
    107410: ("Arma 3", 233780), 1874880: ("Arma Reforger", 1890870),
    221100: ("DayZ", 223350), 393380: ("Squad", 403240), 222880: ("Insurgency", 237410),
    581320: ("Insurgency: Sandstorm", 581330), 447820: ("Day of Infamy", 462310),
    232090: ("Killing Floor 2", 232130), 1250: ("Killing Floor", 215350),
    629760: ("MORDHAU", 629800), 736220: ("Post Scriptum", 746200),
    282440: ("Quake Live", 349090), 1517290: ("Battlefield 2042", None),

    # --- Racing / sim ---
    227300: ("Euro Truck Simulator 2", 1948160), 270880: ("American Truck Simulator", 2239530),
    244210: ("Assetto Corsa", 302550), 805550: ("Assetto Corsa Competizione", None),
    365960: ("rFactor 2", None), 228380: ("Wreckfest", 361580),
    1248130: ("Farming Simulator 22", None), 2300320: ("Farming Simulator 25", None),
}
