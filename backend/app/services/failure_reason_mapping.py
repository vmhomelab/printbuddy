"""Translate Printbuddy's existing failure information into "Report failed print" reason codes.

Two kinds of input exist in Printbuddy:

* ``failure_reason`` text on print log entries / archives. It is either written
  automatically ("Layer shift", "Filament runout", "Clogged nozzle",
  "User cancelled", "Stale - ...") or picked by a person in the Edit Archive
  dialog, which stores the *translated* label of the language that was active.
  ``reason_for_text`` maps every known label in all languages.
* Bambu HMS error codes ("0300_4006"). ``reason_for_hms`` maps them. Printbuddy
  does not keep the HMS code of a finished print, so this is used for the
  printer's live errors (pop-up suggestion) and for queue items whose
  error_message carries the codes.

Mapping results:
* a reason code such as ``fail_reason_01`` -> counts for that reason
* ``SKIP`` -> not a failure cause (e.g. "User cancelled", "paused by user")
* ``None`` -> nothing known; imported prints then land in ``UNASSIGNED``
"""

import re

R01_CLOGGED_NOZZLE = "fail_reason_01"
R02_WARPING = "fail_reason_02"
R03_LAYER_SHIFT = "fail_reason_03"
R04_SLICING = "fail_reason_04"
R05_RUN_OUT = "fail_reason_05"
R06_HARDWARE = "fail_reason_06"
R07_EXTERNAL = "fail_reason_07"
R08_TANGLED = "fail_reason_08"
R09_MAINTENANCE = "fail_reason_09"
R10_POOR_QUALITY = "fail_reason_10"
R11_OTHER = "fail_reason_11"
R12_SPAGHETTI = "fail_reason_12"
R13_FEEDING = "fail_reason_13"
R14_PREPARATION = "fail_reason_14"

# Imported print runs whose cause can't be told. Not selectable in the pop-up;
# shown in the statistics so nothing gets lost, and can be reassigned there.
UNASSIGNED = "unassigned"

# Marker: "this is not a failure cause" (cancel, pause, info message, laser module, ...).
SKIP = "skip"

# ---------------------------------------------------------------------------
# failure_reason text -> reason
# ---------------------------------------------------------------------------

# Labels of the Edit Archive dialog (editArchive.failureReasons.*) in every
# language Printbuddy ships, plus the texts Printbuddy writes automatically.
_TEXT_LABELS: dict[str, tuple[str, ...]] = {
    # adhesionFailure
    R02_WARPING: (
        "Haftungsfehler",
        "Adhesion failure",
        "Fallo de adhesión",
        "Défaut d'adhésion",
        "Fallimento adesione",
        "定着不良",
        "Falha de adesão",
        "附着力失败",
        "附著力失敗",
        # warping
        "Verformung",
        "Warping",
        "Alabeo",
        "Warping (Déformation)",
        "Deformazione",
        "反り",
        "Empenamento",
        "翘曲",
        "翹曲",
    ),
    # spaghettiDetached
    R12_SPAGHETTI: (
        "Spaghetti / Abgelöst",
        "Spaghetti / Detached",
        "Espagueti / Desprendido",
        "Spaghetti / Détaché",
        "Spaghetti / staccato",
        "スパゲッティ / 剥離",
        "Spaghetti / Destacado",
        "拉丝 / 脱落",
        "拉絲 / 脫落",
    ),
    # layerShift (the English label is also the automatic text)
    R03_LAYER_SHIFT: (
        "Schichtversatz",
        "Layer shift",
        "Desplazamiento de capa",
        "Décalage de couche",
        "Spostamento layer",
        "レイヤーシフト",
        "Deslocamento de camada",
        "层偏移",
        "層偏移",
    ),
    # cloggedNozzle (English = automatic text)
    R01_CLOGGED_NOZZLE: (
        "Verstopfte Düse",
        "Clogged nozzle",
        "Boquilla obstruida",
        "Buse bouchée",
        "Ugello intasato",
        "ノズル詰まり",
        "Bico entupido",
        "喷嘴堵塞",
        "噴嘴堵塞",
    ),
    # filamentRunout (English = automatic text)
    R05_RUN_OUT: (
        "Filament aufgebraucht",
        "Filament runout",
        "Agotamiento del filamento",
        "Filament fini",
        "Filamento esaurito",
        "フィラメント切れ",
        "Fim do filamento",
        "耗材用完",
    ),
    # stringing + underExtrusion
    R10_POOR_QUALITY: (
        "Fadenziehen",
        "Stringing",
        "Hilos",
        "Stringing (Cheveux d'ange)",
        "Filamento",
        "糸引き",
        "Fios",
        "拉丝",
        "拉絲",
        "Unterextrusion",
        "Under-extrusion",
        "Subextrusión",
        "Sous-extrusion",
        "Sotto-estrusione",
        "押出不足",
        "Subextrusão",
        "挤出不足",
        "擠出不足",
    ),
    # powerFailure
    R07_EXTERNAL: (
        "Stromausfall",
        "Power failure",
        "Corte de corriente",
        "Coupure courant",
        "Mancanza corrente",
        "電源障害",
        "Falha de energia",
        "断电",
        "斷電",
    ),
    # other
    R11_OTHER: ("Sonstiges", "Other", "Otro", "Autre", "Altro", "その他", "Outro", "其他"),
    # userCancelled (also the automatic text) -> not a failure cause
    SKIP: (
        "Vom Benutzer abgebrochen",
        "User cancelled",
        "Cancelada por el usuario",
        "Annulé par l'utilisateur",
        "Annullato dall'utente",
        "ユーザーによるキャンセル",
        "Cancelado pelo usuário",
        "用户取消",
        "使用者取消",
    ),
}

# Texts Printbuddy writes by itself (as opposed to a person picking a label).
AUTOMATIC_TEXTS = {"Layer shift", "Filament runout", "Clogged nozzle", "User cancelled"}

_TEXT_TO_REASON: dict[str, str] = {
    label.casefold(): reason for reason, labels in _TEXT_LABELS.items() for label in labels
}


def reason_for_text(text: str | None) -> str | None:
    """Reason code, SKIP, or None (empty / unknown text)."""
    value = (text or "").strip()
    if not value:
        return None
    if value.casefold().startswith("stale"):
        # "Stale - print likely cancelled or failed without status update"
        return SKIP
    return _TEXT_TO_REASON.get(value.casefold())


def is_automatic_text(text: str | None) -> bool:
    value = (text or "").strip()
    return value in AUTOMATIC_TEXTS or value.casefold().startswith("stale")


# ---------------------------------------------------------------------------
# Bambu HMS code -> reason
# ---------------------------------------------------------------------------
# Keys are normalised codes (see _normalise_hms): AMS units, AMS-HT units and
# AMS lite slots share one entry; "AMS" = 07xx/18xx unit, "AMSX" = external
# spool / extruder variant (07FE, 07FF, 18FE, 18FF), "LITE" = 1200-1203,
# "LITEX" = 12FF. Every code Printbuddy knows is listed, SKIP included, so the
# review sheet shows a decision for each one.

_S = SKIP
HMS_RULES: dict[str, str] = {
    # ---- 03: toolhead / motion / chamber ----
    "0300_4000": R03_LAYER_SHIFT,  # Z axis homing failed
    "0300_4001": R06_HARDWARE,  # timed out waiting for nozzle to cool
    "0300_4002": R09_MAINTENANCE,  # auto bed leveling failed
    "0300_4005": R06_HARDWARE,  # hotend cooling fan speed abnormal
    "0300_4006": R01_CLOGGED_NOZZLE,  # nozzle is clogged
    "0300_4008": R13_FEEDING,  # AMS failed to change filament
    "0300_4009": R03_LAYER_SHIFT,  # homing XY failed
    "0300_400A": R09_MAINTENANCE,  # resonance frequency identification failed
    "0300_400B": R06_HARDWARE,  # internal communication exception
    "0300_400C": _S,  # task was canceled (same as "User cancelled")
    "0300_400D": R07_EXTERNAL,  # resume failed after power loss
    "0300_400E": R06_HARDWARE,  # motor self-check failed
    "0300_400F": R06_HARDWARE,  # power supply voltage mismatch
    "0300_4010": R09_MAINTENANCE,  # nozzle offset calibration failed
    "0300_4011": R09_MAINTENANCE,  # flow dynamics calibration failed
    "0300_4013": R14_PREPARATION,  # can't print while AMS is drying
    "0300_4014": R06_HARDWARE,  # homing Z failed: temperature control
    "0300_4015": R09_MAINTENANCE,  # nozzle clumping detection calibration failed
    "0300_4016": R09_MAINTENANCE,  # nozzle cleaning failed
    "0300_401F": R14_PREPARATION,  # hotend not installed
    "0300_4020": R06_HARDWARE,  # nozzle presence detection failed
    "0300_4021": R06_HARDWARE,  # nozzle offset sensor signal abnormal
    "0300_4042": _S,  # laser safety window
    "0300_4044": R06_HARDWARE,  # flame sensor abnormal
    "0300_404B": R07_EXTERNAL,  # aborted: front door / top cover open
    "0300_404D": _S,  # too hot to restart (wait message)
    "0300_4050": R06_HARDWARE,  # live view camera calibration timeout
    "0300_4052": _S,  # blade Z homing (cutting module)
    "0300_4057": R03_LAYER_SHIFT,  # Z step loss
    "0300_4066": R09_MAINTENANCE,  # motion precision calibration failed
    "0300_4067": R09_MAINTENANCE,  # calibration result over threshold
    "0300_4068": R03_LAYER_SHIFT,  # step loss during motion accuracy enhancement
    "0300_8000": _S,  # paused for unknown reason
    "0300_8001": _S,  # paused by the user
    "0300_8002": R02_WARPING,  # first layer defects (Micro Lidar)
    "0300_8003": R12_SPAGHETTI,  # spaghetti (AI)
    "0300_8004": R05_RUN_OUT,  # filament ran out
    "0300_8005": R06_HARDWARE,  # toolhead front cover fell off
    "0300_8006": R14_PREPARATION,  # build plate marker not detected
    "0300_8007": R07_EXTERNAL,  # power loss during print
    "0300_8008": R06_HARDWARE,  # nozzle temperature malfunction
    "0300_8009": R06_HARDWARE,  # heatbed temperature malfunction
    "0300_800A": R09_MAINTENANCE,  # filament pile-up in waste chute
    "0300_800B": R13_FEEDING,  # cutter stuck
    "0300_800C": R03_LAYER_SHIFT,  # skipped step detected
    "0300_800D": R10_POOR_QUALITY,  # extruder not extruding normally
    "0300_800E": R06_HARDWARE,  # print file not available (storage removed)
    "0300_800F": R07_EXTERNAL,  # door open, paused
    "0300_8010": R06_HARDWARE,  # hotend cooling fan speed abnormal
    "0300_8011": R04_SLICING,  # build plate differs from G-code
    "0300_8013": _S,  # pause command in the print file
    "0300_8014": R12_SPAGHETTI,  # nozzle covered with filament
    "0300_8015": R05_RUN_OUT,  # external spool ran out
    "0300_8016": R01_CLOGGED_NOZZLE,  # nozzle clogged with filament
    "0300_8017": R14_PREPARATION,  # foreign objects on heatbed
    "0300_8018": R06_HARDWARE,  # chamber temperature malfunction
    "0300_8019": R14_PREPARATION,  # no build plate
    "0300_801A": R01_CLOGGED_NOZZLE,  # filament extrusion error
    "0300_801B": R06_HARDWARE,  # nozzle temperature problem / connector
    "0300_801C": R01_CLOGGED_NOZZLE,  # extrusion resistance abnormal
    "0300_801D": R06_HARDWARE,  # extruder servo position sensor
    "0300_801E": R01_CLOGGED_NOZZLE,  # extrusion motor overloaded
    "0300_8021": R14_PREPARATION,  # nozzle not (properly) installed
    "0300_8022": R03_LAYER_SHIFT,  # heatbed obstructed moving down
    "0300_8028": R06_HARDWARE,  # nozzle offset calibration sensor error
    "0300_8041": R06_HARDWARE,  # platform detection timeout
    "0300_8042": R07_EXTERNAL,  # door open, paused
    "0300_8043": _S,  # laser module abnormal
    "0300_8044": R07_EXTERNAL,  # fire detected in the chamber
    "0300_8045": _S,  # material detection timeout (laser)
    "0300_8046": R06_HARDWARE,  # foreign object detection timeout
    "0300_8047": R06_HARDWARE,  # quick-release lever detection timeout
    "0300_8048": _S,  # laser module unlock
    "0300_8049": R14_PREPARATION,  # current plate invalid
    "0300_804A": _S,  # emergency stop button installation
    "0300_804B": _S,  # laser safety window open
    "0300_804E": _S,  # detach laser/cutting module
    "0300_804F": _S,  # loading with laser/cutting module
    "0300_8050": _S,  # 40 W laser not supported
    "0300_8051": _S,  # cutting module dropped
    "0300_8053": _S,  # laser module mounting
    "0300_8054": _S,  # place paper (print then cut)
    "0300_8055": R04_SLICING,  # module on toolhead doesn't match the task
    "0300_8057": _S,  # rotary attachment
    "0300_8058": _S,  # rotary attachment
    "0300_8061": R06_HARDWARE,  # airflow system air door
    "0300_8062": R07_EXTERNAL,  # chamber too hot
    "0300_8063": R07_EXTERNAL,  # chamber too hot
    "0300_8064": R07_EXTERNAL,  # chamber too hot
    "0300_8065": R06_HARDWARE,  # MC module too hot
    "0300_8071": R06_HARDWARE,  # enhanced cooling fan malfunction
    "0300_807D": _S,  # fire extinguisher
    "0300_807E": _S,  # fire extinguisher
    "0300_807F": _S,  # fire extinguisher
    "0300_8080": _S,  # fire extinguisher
    "0300_8081": _S,  # fire extinguisher
    "0300_8082": _S,  # fire extinguisher
    "0300_C012": _S,  # heat nozzle above 170 °C (instruction)
    "0300_C056": R07_EXTERNAL,  # minor fire detected
    "0300_C070": _S,  # fire extinguisher ready
    # ---- 05: system, network, firmware, accessories ----
    "0500_4001": _S,  # cloud connection
    "0500_4002": R04_SLICING,  # unsupported file path or name
    "0500_4003": R04_SLICING,  # unable to parse the file
    "0500_4004": _S,  # device busy
    "0500_4005": _S,  # firmware update running
    "0500_4006": R06_HARDWARE,  # not enough storage
    "0500_4007": R06_HARDWARE,  # repair upgrade required
    "0500_4008": R06_HARDWARE,  # starting printing failed
    "0500_4009": _S,  # log upload running
    "0500_400A": R04_SLICING,  # file name not supported
    "0500_400B": R06_HARDWARE,  # problem downloading the file
    "0500_400C": R14_PREPARATION,  # insert a MicroSD card
    "0500_400D": R06_HARDWARE,  # run a self-test
    "0500_400E": _S,  # printing was cancelled
    "0500_400F": _S,  # AMS upgrade
    "0500_4010": _S,  # AMS upgrade
    "0500_4011": _S,  # upgrade
    "0500_4012": _S,  # upgrade
    "0500_4013": _S,  # AMS upgrade
    "0500_4014": R04_SLICING,  # slicing for the print job failed
    "0500_4015": R06_HARDWARE,  # not enough storage
    "0500_4016": R06_HARDWARE,  # MicroSD write-protected
    "0500_4017": _S,  # binding
    "0500_4018": _S,  # binding
    "0500_4019": _S,  # binding
    "0500_401A": _S,  # cloud
    "0500_401B": _S,  # cloud
    "0500_401C": _S,  # cloud
    "0500_401D": _S,  # cloud
    "0500_401E": _S,  # cloud
    "0500_401F": _S,  # authorization
    "0500_4020": _S,  # cloud
    "0500_4021": _S,  # cloud
    "0500_4022": _S,  # cloud
    "0500_4023": _S,  # cloud
    "0500_4024": _S,  # cloud
    "0500_4025": _S,  # cloud
    "0500_4026": _S,  # cloud
    "0500_4027": _S,  # cloud
    "0500_4028": _S,  # cloud
    "0500_4029": _S,  # cloud
    "0500_402A": _S,  # router connection
    "0500_402B": _S,  # router password
    "0500_402C": _S,  # IP address
    "0500_402D": R06_HARDWARE,  # system exception
    "0500_402E": _S,  # USB file system
    "0500_402F": R06_HARDWARE,  # MicroSD damaged
    "0500_4030": _S,  # upgrading
    "0500_4031": _S,  # accessory firmware
    "0500_4033": R06_HARDWARE,  # AMS firmware mismatch
    "0500_4034": _S,  # laser firmware
    "0500_4035": R06_HARDWARE,  # BirdsEye camera malfunction
    "0500_4037": R04_SLICING,  # sliced file not for this printer model
    "0500_4038": R04_SLICING,  # nozzle diameter differs from file
    "0500_4039": _S,  # laser/cutting module
    "0500_403A": R07_EXTERNAL,  # temperature too low
    "0500_403B": _S,  # laser/cutting tasks
    "0500_403C": R04_SLICING,  # nozzle setting differs from file
    "0500_403D": R14_PREPARATION,  # toolhead module not set up
    "0500_403E": _S,  # toolhead doesn't support initialisation
    "0500_403F": R06_HARDWARE,  # failed to download print job
    "0500_4040": _S,  # AMS power limit (drying)
    "0500_4041": _S,  # AMS drying during print
    "0500_4042": _S,  # power limit (drying)
    "0500_4043": _S,  # power limit (drying)
    "0500_4044": R06_HARDWARE,  # BirdsEye camera malfunction
    "0500_4045": _S,  # hotend check running
    "0500_4050": R06_HARDWARE,  # error on the print board
    "0500_4052": R06_HARDWARE,  # error on the hotend
    "0500_4054": _S,  # error on the (cutting) mat
    "0500_405D": _S,  # laser module serial
    "0500_4065": _S,  # laser/cutting platform
    "0500_4070": R14_PREPARATION,  # laser/cutter connected, can't 3D print
    "0500_4075": _S,  # laser platform
    "0500_4076": _S,  # laser platform
    "0500_4096": R06_HARDWARE,  # can't detect AMS-HT
    "0500_4097": _S,  # can't detect laser module
    "0500_4098": R06_HARDWARE,  # can't detect AMS
    "0500_4099": _S,  # cutting module firmware
    "0500_409A": _S,  # air pump firmware
    "0500_409B": _S,  # laser module firmware
    "0500_409C": R06_HARDWARE,  # AMS-HT firmware mismatch
    "0500_409D": R06_HARDWARE,  # AMS firmware mismatch
    "0500_409E": _S,  # can't detect cutting module
    "0500_409F": _S,  # can't detect air pump
    "0500_40A0": _S,  # rotary attachment
    "0500_40A1": _S,  # fire extinguishing system
    "0500_40A2": R06_HARDWARE,  # AMS-HT communication abnormal
    "0500_40A3": R06_HARDWARE,  # AMS communication abnormal
    "0500_40A4": R06_HARDWARE,  # too many AMS units
    "0500_40A5": R06_HARDWARE,  # too many AMS units
    "0500_8013": R06_HARDWARE,  # print file not available
    "0500_8036": R04_SLICING,  # sliced file differs from printer model
    "0500_803C": R04_SLICING,  # nozzle setting differs from file
    "0500_8040": R06_HARDWARE,  # toolhead front cover detached
    "0500_8041": _S,  # filament too cold (question)
    "0500_8048": _S,  # toolhead module not calibrated (laser/cutter)
    "0500_8051": R04_SLICING,  # build plate differs from G-code
    "0500_8053": R04_SLICING,  # nozzle mismatch with sliced file
    "0500_8055": _S,  # laser/cutting platform
    "0500_8056": _S,  # laser/cutting platform
    "0500_8058": _S,  # cutting mat
    "0500_8059": _S,  # cutting platform
    "0500_805A": _S,  # cutting mat
    "0500_805B": _S,  # cutting mat
    "0500_805C": _S,  # cutting mat
    "0500_805E": _S,  # cutting module serial
    "0500_8060": R14_PREPARATION,  # toolhead module doesn't meet requirements
    "0500_8061": R14_PREPARATION,  # no print plate detected
    "0500_8062": R14_PREPARATION,  # print plate marker not detected
    "0500_8063": _S,  # laser platform
    "0500_8064": _S,  # laser platform
    "0500_8066": _S,  # cutting platform
    "0500_8067": _S,  # cutting mat
    "0500_8068": _S,  # cutting mat
    "0500_8069": R14_PREPARATION,  # hotends not recognised
    "0500_806A": R14_PREPARATION,  # hotends not recognised
    "0500_806B": R14_PREPARATION,  # quick-release lever not locked
    "0500_806C": _S,  # cutting platform
    "0500_806D": _S,  # material not detected (laser)
    "0500_806E": R14_PREPARATION,  # foreign objects on heatbed
    "0500_806F": _S,  # cutting mat
    "0500_8071": _S,  # cutting platform
    "0500_8072": R09_MAINTENANCE,  # live view camera blocked
    "0500_8073": R09_MAINTENANCE,  # heatbed limit block dirty
    "0500_8074": _S,  # laser platform
    "0500_8077": _S,  # visual marker paper
    "0500_8078": R04_SLICING,  # material differs from sliced file
    "0500_8079": _S,  # laser test material
    "0500_807A": _S,  # foreign object detection not working (info)
    "0500_807B": _S,  # cutting platform
    "0500_807C": _S,  # cutting platform
    "0500_807D": _S,  # cutting platform
    "0500_807E": _S,  # cutting mat
    "0500_8080": R14_PREPARATION,  # hotends not installed
    "0500_8081": R14_PREPARATION,  # hotends not installed
    "0500_8082": _S,  # acrylic protective film
    "0500_8083": _S,  # material in mounting calibration
    "0500_8084": R09_MAINTENANCE,  # live view camera dirty
    "0500_8085": R09_MAINTENANCE,  # toolhead camera obstructed
    "0500_8086": R09_MAINTENANCE,  # toolhead camera dirty
    "0500_8087": R09_MAINTENANCE,  # BirdsEye camera obstructed
    "0500_8088": R09_MAINTENANCE,  # BirdsEye camera dirty
    "0500_8089": _S,  # presence check
    "0500_808A": R06_HARDWARE,  # BirdsEye camera offset
    "0500_808B": R06_HARDWARE,  # BirdsEye camera setup failed
    "0500_808C": R14_PREPARATION,  # build plate offset
    "0500_808D": _S,  # cutting module calibration
    "0500_808E": R06_HARDWARE,  # BirdsEye camera initialisation failed
    "0500_808F": R09_MAINTENANCE,  # nozzle camera lens dirty
    "0500_8090": _S,  # printing paper (print then cut)
    "0500_8091": _S,  # cutting module calibration
    "0500_8092": R06_HARDWARE,  # toolhead camera initialisation failed
    "0500_8093": R09_MAINTENANCE,  # nozzle silicone sleeve missing
    "0500_80A0": _S,  # visual encoder board
    "0500_C010": R06_HARDWARE,  # MicroSD read/write exception
    "0500_C032": _S,  # drying stopped (laser/cutting module)
    "0500_C036": _S,  # detach laser/cutting module
    "0500_C07F": _S,  # device busy
    "0501_4031": _S,  # binding
    "0501_4032": _S,  # binding
    "0501_4033": _S,  # app region
    "0501_4034": R04_SLICING,  # slicing progress stalled, task exited
    "0501_4035": _S,  # binding
    "0501_4038": _S,  # region settings
    "0501_4039": _S,  # login expired
    "0502_4001": _S,  # current filament will be used (info)
    "0502_4002": _S,  # run motion accuracy calibration (info)
    "0502_4003": _S,  # motion accuracy setting while printing
    "0502_4004": R04_SLICING,  # features not supported by device
    "0502_4005": R14_PREPARATION,  # AMS not calibrated
    "0502_4006": _S,  # unknown module
    "0502_400D": R14_PREPARATION,  # filament loading not completed
    "0502_400E": R14_PREPARATION,  # cold pull not completed
    "0502_4013": _S,  # 40 W laser
    "0502_C00F": _S,  # device busy
    "0502_C010": _S,  # power limit
    "0502_C011": _S,  # 2D mode
    "0502_C012": _S,  # task can't be paused
    "0502_C014": _S,  # AMS remaining filament estimation
    "0502_C024": _S,  # flow calibration storage full
    "05FE_8053": R04_SLICING,  # nozzle doesn't match sliced file
    "05FE_8069": R14_PREPARATION,  # hotend not recognised
    "05FE_806A": R14_PREPARATION,  # hotend not recognised
    "05FE_8080": R14_PREPARATION,  # hotend not installed
    "05FE_8081": R14_PREPARATION,  # hotend not installed
    # ---- 07 / 18: AMS and AMS-HT units ----
    "AMS_4001": R14_PREPARATION,  # AMS disabled but filament still loaded
    "AMS_4025": _S,  # failed to read filament information (RFID)
    "AMS_8001": R13_FEEDING,  # failed to cut the filament
    "AMS_8002": R13_FEEDING,  # cutter stuck
    "AMS_8003": R01_CLOGGED_NOZZLE,  # failed to pull filament out of extruder (clog / broken)
    "AMS_8004": R13_FEEDING,  # failed to pull back filament
    "AMS_8005": R13_FEEDING,  # failed to send out filament
    "AMS_8006": R13_FEEDING,  # unable to feed filament into the extruder
    "AMS_8007": R01_CLOGGED_NOZZLE,  # extruding filament failed
    "AMS_800A": R13_FEEDING,  # PTFE tube disconnected
    "AMS_8010": R08_TANGLED,  # assist motor overloaded: entangled filament / stuck spool
    "AMS_8011": R05_RUN_OUT,  # AMS filament ran out
    "AMS_8012": R13_FEEDING,  # failed to get AMS mapping table
    "AMS_8013": R01_CLOGGED_NOZZLE,  # timeout purging old filament
    "AMS_8016": R10_POOR_QUALITY,  # extruder not extruding normally
    "AMS_8017": R14_PREPARATION,  # AMS is drying
    "AMS_8021": R06_HARDWARE,  # AMS setup failed
    "AMS_8023": _S,  # AMS cooling failed (drying)
    "AMS_C069": _S,  # drying error
    "AMS_C06A": _S,  # drying
    "AMS_C06B": _S,  # drying
    "AMS_C06C": _S,  # drying
    "AMS_C06D": _S,  # drying
    "AMS_C06E": _S,  # drying
    "AMSX_8001": R13_FEEDING,  # failed to cut the filament
    "AMSX_8002": R13_FEEDING,  # cutter stuck
    "AMSX_8003": _S,  # pull out the filament (instruction)
    "AMSX_8004": R13_FEEDING,  # failed to pull back from extruder
    "AMSX_8005": R13_FEEDING,  # failed to feed filament outside the AMS
    "AMSX_8006": _S,  # feed filament into the PTFE tube (instruction)
    "AMSX_8007": _S,  # observe the nozzle (instruction)
    "AMSX_8010": R08_TANGLED,  # external spool or filament stuck
    "AMSX_8011": R05_RUN_OUT,  # external filament ran out
    "AMSX_8012": R13_FEEDING,  # failed to get mapping table
    "AMSX_8013": R01_CLOGGED_NOZZLE,  # timeout purging old filament
    "AMSX_8021": R06_HARDWARE,  # AMS setup failed
    "AMSX_8020": R06_HARDWARE,  # extruder change failed
    "AMSX_8024": R06_HARDWARE,  # extruder position calibration failed
    "AMSX_8025": _S,  # cold pull timed out
    "AMSX_8030": R05_RUN_OUT,  # filament from the slicer used up
    "AMSX_4001": R14_PREPARATION,  # AMS disabled but filament still loaded
    "AMSX_C003": _S,  # instruction
    "AMSX_C006": _S,  # instruction
    "AMSX_C008": _S,  # instruction
    "AMSX_C009": _S,  # instruction
    "AMSX_C00A": _S,  # instruction
    "AMSX_C010": _S,  # instruction
    "AMSX_C011": _S,  # instruction
    "AMSX_C012": _S,  # instruction
    # ---- 12: AMS lite ----
    "LITE_4001": R14_PREPARATION,  # AMS disabled but filament still loaded
    "LITE_8001": R13_FEEDING,  # cutting failed
    "LITE_8002": R13_FEEDING,  # cutter stuck
    "LITE_8003": R01_CLOGGED_NOZZLE,  # failed to pull out of extruder (clog / broken)
    "LITE_8004": R13_FEEDING,  # failed to pull back
    "LITE_8005": R13_FEEDING,  # failed to feed / not inserted
    "LITE_8006": R13_FEEDING,  # failed to feed into the toolhead
    "LITE_8007": R01_CLOGGED_NOZZLE,  # failed to extrude
    "LITE_8010": R08_TANGLED,  # filament or spool stuck
    "LITE_8011": R05_RUN_OUT,  # filament ran out
    "LITE_8012": R13_FEEDING,  # failed to get mapping table
    "LITE_8013": R01_CLOGGED_NOZZLE,  # timeout purging old filament
    "LITE_8014": R13_FEEDING,  # filament location in toolhead not found
    "LITE_8015": R13_FEEDING,  # failed to pull back / broken in PTFE
    "LITE_8016": R10_POOR_QUALITY,  # extruder not extruding normally
    "LITEX_4001": R14_PREPARATION,  # AMS disabled but filament still loaded
    "LITEX_8001": R13_FEEDING,  # cutting failed
    "LITEX_8002": R13_FEEDING,  # cutter stuck
    "LITEX_8003": _S,  # pull out the filament (instruction)
    "LITEX_8004": R13_FEEDING,  # failed to pull back
    "LITEX_8005": R13_FEEDING,  # failed to feed
    "LITEX_8006": _S,  # feed filament into the PTFE tube (instruction)
    "LITEX_8007": _S,  # check nozzle (instruction)
    "LITEX_8010": R08_TANGLED,  # filament or spool stuck
    "LITEX_8011": R05_RUN_OUT,  # filament ran out
    "LITEX_8012": R13_FEEDING,  # failed to get mapping table
    "LITEX_8013": R01_CLOGGED_NOZZLE,  # timeout purging old filament
    "LITEX_C003": _S,  # instruction
    "LITEX_C006": _S,  # instruction
    # ---- 0C: cameras and AI monitoring ----
    "0C00_4020": R06_HARDWARE,  # BirdsEye camera setup failed
    "0C00_4021": R06_HARDWARE,  # BirdsEye camera setup failed
    "0C00_4022": R06_HARDWARE,  # BirdsEye camera setup failed
    "0C00_4024": R06_HARDWARE,  # BirdsEye camera installed offset
    "0C00_4025": R09_MAINTENANCE,  # BirdsEye camera dirty
    "0C00_4026": R06_HARDWARE,  # live view camera initialisation failed
    "0C00_4027": R06_HARDWARE,  # live view camera calibration failed
    "0C00_4029": _S,  # material not detected (laser)
    "0C00_402A": _S,  # visual marker paper
    "0C00_402C": R06_HARDWARE,  # device data link error
    "0C00_402D": R06_HARDWARE,  # toolhead camera not working
    "0C00_403D": _S,  # vision encoder plate
    "0C00_403E": R09_MAINTENANCE,  # high-precision nozzle offset calibration failed
    "0C00_4041": R09_MAINTENANCE,  # toolhead camera calibration failed (marker dirty)
    "0C00_8001": R02_WARPING,  # first layer defects
    "0C00_8005": R09_MAINTENANCE,  # purged filament piled up in waste chute
    "0C00_8009": R14_PREPARATION,  # build plate marker not found
    "0C00_800B": R14_PREPARATION,  # heatbed marker not detected
    "0C00_8015": R14_PREPARATION,  # objects on the platform
    "0C00_8016": _S,  # foreign object detection not working (info)
    "0C00_8017": R14_PREPARATION,  # foreign objects on the platform
    "0C00_8018": _S,  # foreign object detection not working (info)
    "0C00_8033": R14_PREPARATION,  # quick-release lever not locked
    "0C00_8034": R06_HARDWARE,  # live view camera initialisation failed
    "0C00_803F": R12_SPAGHETTI,  # nozzle clumping (AI)
    "0C00_8040": R10_POOR_QUALITY,  # air printing (AI)
    "0C00_8042": R12_SPAGHETTI,  # spaghetti (AI)
    "0C00_8043": R12_SPAGHETTI,  # (AI print monitor)
    "0C00_C003": R02_WARPING,  # possible first layer defects
    "0C00_C004": R12_SPAGHETTI,  # possible spaghetti
    "0C00_C006": _S,  # purged filament may have piled up (info)
    # ---- 10: slicer settings warnings ----
    "1000_C001": _S,
    "1000_C002": _S,
    "1000_C003": _S,
    "1001_4001": R04_SLICING,  # timelapse not supported with spiral vase
    "1001_4002": R04_SLICING,  # timelapse not supported with "by object"
    "1001_8003": _S,
    "1001_8004": _S,
}

_HMS_RE = re.compile(r"^([0-9A-F]{4})_([0-9A-F]{4})$")
_HMS_IN_TEXT_RE = re.compile(r"\[([0-9A-Fa-f]{4}_[0-9A-Fa-f]{4})\]")


def normalise_hms(short_code: str) -> str | None:
    """Collapse unit / slot variants onto the key used in HMS_RULES."""
    match = _HMS_RE.match((short_code or "").strip().upper())
    if not match:
        return None
    module, error = match.groups()
    family = module[:2]
    if family in ("07", "18"):
        return f"{'AMSX' if module[2:] in ('FE', 'FF') else 'AMS'}_{error}"
    if family == "12":
        return f"{'LITEX' if module[2:] == 'FF' else 'LITE'}_{error}"
    if family == "05":
        if module.startswith("058"):  # AMS-HT A..H
            return f"0500_{error}"
        if error in ("40A3", "409D", "4098") and module in ("0500", "0501", "0502", "0503"):
            return f"0500_{error}"
        if module == "0501" and "4017" <= error <= "4029":  # binding / cloud, same as 0500
            return f"0500_{error}"
        if module == "05FF":  # right hotend = same as left (05FE)
            return f"05FE_{error}"
    return f"{module}_{error}"


def reason_for_hms(short_code: str) -> str | None:
    """Reason code, SKIP, or None (code not in the table)."""
    key = normalise_hms(short_code)
    return HMS_RULES.get(key) if key else None


def hms_codes_in_text(text: str | None) -> list[str]:
    """Short codes in a queue error_message like "[0300_4006] The nozzle is clogged.; [...]"."""
    return [code.upper() for code in _HMS_IN_TEXT_RE.findall(text or "")]


def reason_for_hms_list(codes: list[str]) -> tuple[str | None, str | None]:
    """First code that maps to a reason -> (reason, code). Severe codes (4xxx, 8xxx) win over info (Cxxx)."""
    ordered = sorted(codes, key=lambda c: 1 if c[5:6] == "C" else 0)
    for code in ordered:
        reason = reason_for_hms(code)
        if reason and reason != SKIP:
            return reason, code
    return None, None


def hms_short_code(attr: int, code: int | str) -> str:
    """ "MMMM_EEEE" from the raw attr/code values of a live HMS error."""
    if isinstance(code, str):
        code_int = int(code.replace("0x", ""), 16) if code else 0
    else:
        code_int = int(code or 0)
    return f"{(int(attr or 0) >> 16) & 0xFFFF:04X}_{code_int & 0xFFFF:04X}"
