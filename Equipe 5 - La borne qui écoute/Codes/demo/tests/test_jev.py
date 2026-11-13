import httpx
import jev
import mapping
import pytest


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_un_seul_appel_avec_toutes_les_questions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"model": jev.MODEL, "answers": {}})

    body = jev.build_request("super balade", mapping.questions("Isère"), "Peuil", "fr")
    raw = jev.decide(body, client=_client(handler))
    assert raw["answers"] == {}
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer k"
    assert body["model"] == "typesafe/jev-1.14"
    assert set(body["questions"]) == set(mapping.questions("Isère"))
    assert "parking" not in body["state"]["contexte"]
    assert body["state"]["transcription"] == "super balade"


def test_sans_cle(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(jev.JevError, match="OPENROUTER_API_KEY"):
        jev.decide({})


@pytest.mark.parametrize(
    "resp",
    [httpx.Response(500, text="boom"), httpx.Response(200, text="pas du json"), httpx.Response(200, json={"x": 1})],
)
def test_erreurs(monkeypatch, resp):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(jev.JevError):
        jev.decide({}, client=_client(lambda req: resp))


def test_erreur_reseau(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def handler(req):
        raise httpx.ConnectError("hors ligne")

    with pytest.raises(jev.JevError, match="réseau"):
        jev.decide({}, client=_client(handler))
