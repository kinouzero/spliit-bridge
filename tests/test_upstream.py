
import app.server as server


def test_upstream_procedure_validation():
    for procedure in ["bad procedure", "bad/procedure", "bad?x=1", ""]:
        try:
            server.upstream_call(procedure)
        except ValueError as exc:
            assert str(exc) == "Invalid upstream procedure"
        else:
            raise AssertionError("Invalid procedure was accepted")


def test_unwrap_trpc():
    payload = {"result": {"data": {"json": {"ok": True}}}}
    assert server.unwrap_trpc(payload) == {"ok": True}


def test_unwrap_trpc_returns_unknown_shape_unchanged():
    payload = {"unexpected": True}
    assert server.unwrap_trpc(payload) == payload


def test_json_bytes_disallows_nan():
    try:
        server.json_bytes({"value": float("nan")})
    except ValueError:
        pass
    else:
        raise AssertionError("NaN should not be serialized")
