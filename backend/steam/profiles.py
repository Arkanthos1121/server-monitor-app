"""Launch profiles for the dedicated servers people actually self-host.

Each profile says how to install and run one game's server. `binary` paths are
relative to the server's install dir. A game with no profile can still be
installed and started by setting launch_cmd explicitly on the server record.

Placeholders expanded at launch time: {dir} {name} {port} {password} {players}
"""

PROFILES = {
    # server_appid: profile
    896660: {  # Valheim
        "game": "Valheim", "port": 2456, "players": 10,
        "linux": "valheim_server.x86_64", "windows": "valheim_server.exe",
        "args": "-nographics -batchmode -name {name} -port {port} -world {name} -password {password} -public 0",
        "needs_password": True, "min_password": 5,
        "query_port_offset": 1,
    },
    2394010: {  # Palworld
        "game": "Palworld", "port": 8211, "players": 32,
        "linux": "PalServer.sh", "windows": "PalServer.exe",
        "args": "-useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS port={port}",
        "query_port": 27015, "rcon_port": 25575, "save_cmd": "Save",
    },
    258550: {  # Rust
        "game": "Rust", "port": 28015, "players": 50,
        "linux": "RustDedicated", "windows": "RustDedicated.exe",
        "args": "-batchmode +server.port {port} +server.hostname \"{name}\" +server.maxplayers {players}",
        "query_port_offset": 1,
    },
    294420: {  # 7 Days to Die
        "game": "7 Days to Die", "port": 26900, "players": 8,
        "linux": "startserver.sh", "windows": "startdedicated.bat",
        "args": "-configfile=serverconfig.xml",
        "query_port": 26900, "rcon_port": 8081, "save_cmd": "saveworld",
    },
    380870: {  # Project Zomboid
        "game": "Project Zomboid", "port": 16261, "players": 16,
        "linux": "start-server.sh", "windows": "StartServer64.bat",
        "args": "-servername {name}",
        "query_port_offset": 1,
    },
    1829350: {  # V Rising
        "game": "V Rising", "port": 9876, "players": 10,
        "linux": "VRisingServer.exe", "windows": "VRisingServer.exe",
        "args": "-persistentDataPath ./save-data -serverName \"{name}\" -gamePort {port}",
        "query_port_offset": 1,
    },
    1690800: {  # Satisfactory
        "game": "Satisfactory", "port": 7777, "players": 4,
        "linux": "FactoryServer.sh", "windows": "FactoryServer.exe",
        "args": "-multihome=0.0.0.0 -Port={port}",
        "query_port": 15777,
    },
    376030: {  # ARK: Survival Evolved
        "game": "ARK: Survival Evolved", "port": 7777, "players": 20,
        "linux": "ShooterGame/Binaries/Linux/ShooterGameServer",
        "windows": "ShooterGame/Binaries/Win64/ShooterGameServer.exe",
        "args": "TheIsland?listen?SessionName=\"{name}\"?Port={port}?MaxPlayers={players}",
        "query_port": 27015, "rcon_port": 27020, "save_cmd": "saveworld",
    },
    2278520: {  # Enshrouded
        "game": "Enshrouded", "port": 15636, "players": 16,
        "linux": "enshrouded_server.exe", "windows": "enshrouded_server.exe",
        "args": "",
        "query_port_offset": 1,
    },
    1963720: {  # Core Keeper
        "game": "Core Keeper", "port": 27015, "players": 8,
        "linux": "_launch.sh", "windows": "CoreKeeperServer.exe",
        "args": "",
        "query_port_offset": 0,
    },
    2857200: {  # Abiotic Factor
        "game": "Abiotic Factor", "port": 7777, "players": 6,
        "linux": "AbioticFactorServer.sh", "windows": "AbioticFactorServer.exe",
        "args": "-Port={port}",
        "query_port_offset": 1,
    },
    740: {  # Counter-Strike 2
        "game": "Counter-Strike 2", "port": 27015, "players": 10,
        "linux": "game/bin/linuxsteamrt64/cs2", "windows": "game/bin/win64/cs2.exe",
        "args": "-dedicated -port {port} +map de_dust2",
        "query_port_offset": 0,
    },
    4020: {  # Garry's Mod
        "game": "Garry's Mod", "port": 27015, "players": 16,
        "linux": "srcds_run", "windows": "srcds.exe",
        "args": "-console -game garrysmod +maxplayers {players} +map gm_construct -port {port}",
        "query_port_offset": 0,
    },
    222860: {  # Left 4 Dead 2
        "game": "Left 4 Dead 2", "port": 27015, "players": 8,
        "linux": "srcds_run", "windows": "srcds.exe",
        "args": "-console -game left4dead2 +map c1m1_hotel -port {port}",
        "query_port_offset": 0,
    },
    232250: {  # Team Fortress 2
        "game": "Team Fortress 2", "port": 27015, "players": 24,
        "linux": "srcds_run", "windows": "srcds.exe",
        "args": "-console -game tf +maxplayers {players} +map cp_dustbowl -port {port}",
        "query_port_offset": 0,
    },
    298740: {  # Space Engineers
        "game": "Space Engineers", "port": 27016, "players": 8,
        "linux": None, "windows": "DedicatedServer64/SpaceEngineersDedicated.exe",
        "args": "-console",
        "query_port_offset": 1, "runner": "wine",
    },
    443030: {  # Conan Exiles
        "game": "Conan Exiles", "port": 7777, "players": 20,
        "linux": None, "windows": "ConanSandboxServer.exe",
        "args": "-log -MaxPlayers={players}",
        "query_port_offset": 1,
    },
    1110390: {  # Unturned
        "game": "Unturned", "port": 27015, "players": 24,
        "linux": "ServerHelper.sh", "windows": "Unturned.exe",
        "args": "+LanServer/{name}",
        "query_port_offset": 1,
    },
    1026340: {  # Barotrauma
        "game": "Barotrauma", "port": 27015, "players": 16,
        "linux": "DedicatedServer", "windows": "DedicatedServer.exe",
        "args": "",
        "query_port_offset": 0,
    },
    2089300: {  # Icarus
        "game": "ICARUS", "port": 17777, "players": 8,
        "linux": "IcarusServer.sh", "windows": "IcarusServer.exe",
        "args": "-Port={port}",
        "query_port_offset": 1,
    },
    2430930: {  # ARK: Survival Ascended
        "game": "ARK: Survival Ascended", "port": 7777, "players": 20,
        "linux": None, "windows": "ShooterGame/Binaries/Win64/ArkAscendedServer.exe",
        "args": "TheIsland_WP?listen?SessionName=\"{name}\"?Port={port}",
        "query_port": 27015, "rcon_port": 27020, "save_cmd": "saveworld", "runner": "proton",
    },
}


def get(server_appid):
    return PROFILES.get(int(server_appid)) if server_appid else None


def query_port(rec: dict):
    """Port to send A2S player-count queries to.

    Most engines listen for queries on the game port plus one; Source games use
    the game port itself. A profile may override with an explicit query_port.
    """
    prof = get(rec.get("server_appid")) or {}
    port = rec.get("port") or prof.get("port")
    if not port:
        return None
    if prof.get("query_port"):
        return prof["query_port"]
    if "query_port_offset" in prof:
        return port + prof["query_port_offset"]
    return port + 1


def save_command(rec: dict):
    """(rcon_port, command) when this game can be told to save over RCON.

    Only games that genuinely speak Source RCON are listed. Rust uses WebSocket
    RCON and Space Engineers has no standard remote console, so those rely on
    SIGTERM triggering the engine's own save-on-exit.
    """
    prof = get(rec.get("server_appid")) or {}
    if not prof.get("save_cmd"):
        return None
    return prof.get("rcon_port"), prof["save_cmd"]


def runner(rec: dict) -> str:
    """How the server binary is launched: native, proton or wine."""
    if rec.get("runner"):
        return rec["runner"]
    return (get(rec.get("server_appid")) or {}).get("runner", "native")
