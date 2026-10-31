import os

from mistralai.client import Mistral, errors

model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
server = os.environ.get("MISTRAL_SERVER_URL")  # None = La Plateforme

with Mistral(api_key=os.environ["MISTRAL_API_KEY"], server_url=server) as client:
    try:
        res = client.chat.complete(
            model=model,
            messages=[{"role": "user", "content": "Was ist ein SLO? Ein Satz."}],
            max_tokens=60,
        )
    except errors.MistralError as e:
        raise SystemExit(f"HTTP {e.status_code}: {e.body}") from None
print(res.choices[0].message.content)
print(res.usage)
