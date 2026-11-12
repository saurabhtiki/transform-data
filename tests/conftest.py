import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from transform_data.state import registry

SALES = (
    "Invoice,Customer ID,Date,Region,Sales,Cost\n"
    "INV-1,C1,01-04-2026,North,1200,800\n"
    'INV-2,C2,15-04-2026,South,"2,500",1900\n'
    "INV-3,C1,03-05-2026,North,700,650\n"
    "INV-3,C1,03-05-2026,North,700,650\n"
    "INV-4,C3,20-05-2026,East,4100,3000\n"
    "INV-5,C4,02-06-2026,West,,400\n"
)
CUSTOMERS = (
    "Customer ID,Name,City\nC1,Asha Traders,Pune\nC2,Ravi Stores,Chennai\nC3,Mehta,Kolkata\n"
)


@pytest.fixture(autouse=True)
def empty_registry():
    """Every test starts and ends with no data in memory."""
    registry.discard_all()
    yield
    registry.discard_all()


def csv_file(name: str, text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


@pytest.fixture
def loaded(client):
    """A client whose session holds sales + customers."""
    client.post(
        "/transform/upload/",
        {"files": [csv_file("sales.csv", SALES), csv_file("customers.csv", CUSTOMERS)]},
    )
    return client


def store_of(client):
    store, _ = registry.for_request(client)
    return store
