from fastapi.testclient import TestClient

from examples.quickstart import app


def test_quickstart_example_runs_end_to_end() -> None:
    query = """
    {
      Team {
        by_filter {
          id
          name
          heroes {
            id
            name
          }
        }
      }
    }
    """

    with TestClient(app) as client:
        response = client.post("/graphql", json={"query": query})

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "Team": {
                "by_filter": [
                    {
                        "id": 1,
                        "name": "Avengers",
                        "heroes": [{"id": 1, "name": "Spider-Man"}],
                    }
                ]
            }
        }
    }
