"""
status.py

Builds the JSON status payload from AppState - shared by the REST
/status endpoint and the WebSocket broadcaster in ws_manager.py, so both
return exactly the same shape and only need updating in one place.
"""

from core.state import AppState


def build_status_payload(state: AppState) -> dict:
    if state.latest is None:
        return {"error": "Poller hasn't completed a cycle yet"}

    result = state.latest
    return {
        "requested_amps": state.requested_amps,
        "charger_state": result.state.charger_state_name,
        "plug_state": result.state.plug_state,
        "vehicle_current_amps": result.state.p1_current,
        "hub_duty_limit_amps": result.state.hub_duty_limit_amps,
        # site_current_amps intentionally left out - no CT clamp is
        # physically installed on that channel yet (see project notes),
        # so the raw reading is just uncalibrated sensor noise, not real
        # data. Add it back once a real clamp is wired in.
        "last_error": state.last_error,
    }
