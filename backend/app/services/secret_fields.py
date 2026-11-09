"""Write-only secrets: notification provider configs, settings, smart plugs.

Responses show a set secret as SECRET_PLACEHOLDER. A config sent back with
the placeholder keeps the stored value, an empty value clears it, and anything
else replaces it. A stored secret is only used for the destination it was
entered for: a config that changes the destination (or the provider type) must
carry the secret again, and a type change must bring a config of its own.
"""

from __future__ import annotations

from typing import Any

from backend.app.core.logging_filters import redact_url_credentials

SECRET_PLACEHOLDER = "********"

# The config fields that hold a credential, per provider type. For Discord and
# the generic webhook the URL itself is commonly the credential.
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "callmebot": ("apikey",),
    "ntfy": ("auth_token",),
    "pushover": ("user_key", "app_token"),
    "telegram": ("bot_token",),
    "email": ("password",),
    "discord": ("webhook_url",),
    "webhook": ("webhook_url", "auth_header"),
    "bark": ("device_key",),
    "gotify": ("app_token",),
    # Printbuddy's Notify: the legacy single-device token. Each entry of its
    # recipients list holds a token too (SECRET_LIST_FIELDS).
    "notify": ("device_token",),
    "homeassistant": (),
}

# Config fields holding a list of entries, each with secret fields of its own:
# Notify sends to every recipient, each with its own device token.
SECRET_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "recipients": ("device_token",),
}

# Every secret field name of every type. Responses mask these whatever the
# provider's type, so a key left over from another type is never shown.
ALL_SECRET_FIELDS = frozenset(field for fields in SECRET_FIELDS.values() for field in fields)

# The config fields that decide where the secrets are sent. Types not listed
# send to a fixed service.
DESTINATION_FIELDS: dict[str, tuple[str, ...]] = {
    "email": ("smtp_server", "smtp_port", "security"),
    "ntfy": ("server",),
    "bark": ("server",),
    "gotify": ("server",),
    "webhook": ("webhook_url",),
    "notify": ("base_url",),
}


class SecretConfigError(ValueError):
    """A config that would reuse a stored secret where it may not."""


def _mask_entries(entries: Any, fields: tuple[str, ...]) -> Any:
    if not isinstance(entries, list):
        return entries
    return [
        {key: (SECRET_PLACEHOLDER if key in fields and value else value) for key, value in entry.items()}
        if isinstance(entry, dict)
        else entry
        for entry in entries
    ]


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """The config as a response shows it: every set secret as the placeholder."""
    masked: dict[str, Any] = {}
    for key, value in config.items():
        if key in ALL_SECRET_FIELDS and value:
            masked[key] = SECRET_PLACEHOLDER
        elif key in SECRET_LIST_FIELDS:
            masked[key] = _mask_entries(value, SECRET_LIST_FIELDS[key])
        else:
            masked[key] = value
    return masked


def same_value(a: Any, b: Any) -> bool:
    """Equal as the edit dialog sends them back: as text, None as empty.

    Not stripped: a sender compares the exact value (" starttls" is not TLS).
    """
    return ("" if a is None else str(a)) == ("" if b is None else str(b))


# What a sender uses for a destination field that is not in the config at all.
_SENDER_DEFAULTS: dict[tuple[str, str], str] = {
    ("email", "security"): "starttls",
    ("notify", "base_url"): "https://push.getnotifyapp.com",
}


def _effective(provider_type: str, config: dict[str, Any], field: str) -> Any:
    if field in config:
        return config[field]
    return _SENDER_DEFAULTS.get((provider_type, field))


def _kept_entries(config: dict[str, Any]) -> list[tuple[str, int, str]]:
    """(list field, index, secret field) of every list entry keeping its secret."""
    kept = []
    for list_key, fields in SECRET_LIST_FIELDS.items():
        entries = config.get(list_key)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            kept.extend((list_key, index, field) for field in fields if entry.get(field) == SECRET_PLACEHOLDER)
    return kept


def has_placeholder(config: dict[str, Any]) -> bool:
    return any(value == SECRET_PLACEHOLDER for value in config.values()) or bool(_kept_entries(config))


def reject_placeholder(config: dict[str, Any]) -> None:
    """A config with nothing stored behind it (a new provider, a test of one)."""
    if has_placeholder(config):
        raise SecretConfigError("Enter the secret values; nothing is stored for this provider yet")


def _stored_entry(stored: dict[str, Any], list_key: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """The stored list entry an incoming one keeps its secret from, by its id.

    A provider saved before it had a list (a single top-level Notify device)
    is the entry the edit dialog shows as id "legacy".
    """
    entries = stored.get(list_key)
    if isinstance(entries, list):
        entry_id = entry.get("id")
        for candidate in entries:
            if isinstance(candidate, dict) and entry_id not in (None, "") and same_value(candidate.get("id"), entry_id):
                return candidate
        return None
    if list_key == "recipients" and entry.get("id") == "legacy":
        return stored
    return None


# The entry field a list entry's secret belongs to: a Notify token is the token
# of one device ID, so it is not kept for another device.
_ENTRY_OWNER_FIELDS: dict[str, str] = {"recipients": "device_id"}


def merge_config(
    stored_type: str,
    stored: dict[str, Any],
    new_type: str,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """The config to use: the placeholder replaced by the stored secret.

    Refused when a placeholder would carry a stored secret to another provider
    type or another destination (or, for a list entry, another device).
    """
    kept = [key for key, value in incoming.items() if value == SECRET_PLACEHOLDER]
    kept_entries = _kept_entries(incoming)
    if not kept and not kept_entries:
        return dict(incoming)
    kept_names = kept + [f"{list_key}[{index}].{field}" for list_key, index, field in kept_entries]
    if new_type != stored_type:
        raise SecretConfigError(f"Enter {', '.join(kept_names)} again for the new provider type")
    unknown = [key for key in kept if key not in ALL_SECRET_FIELDS or not stored.get(key)]
    if unknown:
        raise SecretConfigError(f"Enter {', '.join(unknown)}; there is no stored value to keep")
    moved = [
        field
        for field in DESTINATION_FIELDS.get(stored_type, ())
        if incoming.get(field) != SECRET_PLACEHOLDER
        and not same_value(_effective(stored_type, incoming, field), _effective(stored_type, stored, field))
    ]
    if moved:
        raise SecretConfigError(f"Enter {', '.join(kept_names)} again: {', '.join(moved)} changed")
    merged = {key: (stored[key] if value == SECRET_PLACEHOLDER else value) for key, value in incoming.items()}
    for list_key in {list_key for list_key, _, _ in kept_entries}:
        entries = []
        for index, entry in enumerate(incoming[list_key]):
            fields = [field for key, i, field in kept_entries if key == list_key and i == index]
            if not fields:
                entries.append(entry)
                continue
            name = f"{list_key}[{index}]"
            source = _stored_entry(stored, list_key, entry)
            if source is None or any(not source.get(field) for field in fields):
                raise SecretConfigError(f"Enter {', '.join(fields)} for {name}; there is no stored value to keep")
            owner = _ENTRY_OWNER_FIELDS.get(list_key)
            if owner and not same_value(entry.get(owner), source.get(owner)):
                raise SecretConfigError(f"Enter {', '.join(fields)} for {name} again: {owner} changed")
            entries.append({**entry, **{field: source[field] for field in fields}})
        merged[list_key] = entries
    return merged


# Settings secrets and the settings that decide where each is sent.
SETTINGS_SECRETS: dict[str, tuple[str, ...]] = {
    "mqtt_password": ("mqtt_broker", "mqtt_port", "mqtt_use_tls"),
    "ha_token": ("ha_url",),
    "obico_ml_token": ("obico_ml_url",),
    "prometheus_token": (),
    "ldap_bind_password": ("ldap_server_url", "ldap_security"),
}

# Settings rows that hold a credential, by name: a Git backup writes them as
# the placeholder and a restore never writes them. By hint rather than by list,
# so a credential setting added later is covered by default.
SECRET_SETTING_KEY_HINTS = ("token", "secret", "password", "access_code", "api_key", "passphrase", "verifier")


def is_secret_setting_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in SECRET_SETTING_KEY_HINTS)


REST_PLUG_URLS = ("rest_on_url", "rest_off_url", "rest_status_url", "rest_power_url", "rest_energy_url")

# Slicer preset keys holding a printer connection's credentials (for a LAN
# printer, its access code). Slicer cloud sync carries them.
PRESET_SECRET_KEYS = ("printhost_apikey", "printhost_password", "printhost_user")


def _mask_url_logins(value: Any) -> Any:
    if isinstance(value, str):
        return redact_url_credentials(value)
    if isinstance(value, list):
        return [_mask_url_logins(item) for item in value]
    return value


def mask_preset(content: Any) -> Any:
    """A slicer preset with its connection credentials shown as the placeholder
    and the login in any of its URLs masked."""
    if not isinstance(content, dict):
        return content
    return {key: _mask_url_logins(value) for key, value in mask_fields(content, PRESET_SECRET_KEYS).items()}


# Smart plug secrets and the fields that decide where each is sent.
SMART_PLUG_SECRETS: dict[str, tuple[str, ...]] = {
    "password": ("plug_type", "ip_address"),
    "rest_headers": ("plug_type", *REST_PLUG_URLS),
}


def mask_fields(values: dict[str, Any], fields: Any) -> dict[str, Any]:
    """values with each set field of ``fields`` shown as the placeholder."""
    return {key: (SECRET_PLACEHOLDER if key in fields and value else value) for key, value in values.items()}


def merge_partial(
    stored: dict[str, Any],
    update: dict[str, Any],
    secrets: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    """A partial update with the placeholder resolved: the secret is kept.

    A secret is kept when it is sent as the placeholder or not sent at all.
    Refused when a kept secret's destination changes, or the placeholder
    stands for a secret that is not stored.
    """
    result = dict(update)
    for secret, destinations in secrets.items():
        sent = secret in update
        if sent and update[secret] == SECRET_PLACEHOLDER:
            if not stored.get(secret):
                raise SecretConfigError(f"Enter {secret}; there is no stored value to keep")
            del result[secret]
        elif sent:
            continue
        if not stored.get(secret):
            continue
        moved = [
            field for field in destinations if field in update and not same_value(update[field], stored.get(field))
        ]
        if moved:
            raise SecretConfigError(f"Enter {secret} again: {', '.join(moved)} changed")
    return result


# The SMTP settings that decide where the stored SMTP password is sent.
SMTP_DESTINATIONS = ("smtp_host", "smtp_port", "smtp_security")
