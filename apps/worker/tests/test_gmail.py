import base64

from portfolio_worker.gmail import decode_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_decode_message_separates_bodies_and_attachments() -> None:
    message = decode_message(
        {
            "id": "synthetic-message",
            "internalDate": "1767225600000",
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "partId": "0",
                        "mimeType": "text/html",
                        "body": {"data": encoded("<p>Synthetic</p>")},
                    },
                    {
                        "partId": "1",
                        "mimeType": "application/pdf",
                        "filename": "synthetic.pdf",
                        "body": {"data": encoded("not-a-real-pdf")},
                    },
                ],
            },
        }
    )
    assert message.message_id == "synthetic-message"
    assert message.html_bodies[0].data == b"<p>Synthetic</p>"
    assert message.attachments[0].filename == "synthetic.pdf"
