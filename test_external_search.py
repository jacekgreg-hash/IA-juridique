from server.candidates.external import search_external
from server.candidates.web_search import WebResult, build_queries


class FakeProvider:
    name = 'fake_web'
    enabled = True

    def __init__(self):
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        return [WebResult(
            title='Nike P-6000 Metallic Silver - Nike FR',
            url='https://www.nike.com/fr/t/chaussure-nike-p-6000-Z6nJN4Ea',
            snippet='Nike P-6000 chaussure de sport Metallic Silver/Sail/Noir. Article CN0149-001.',
            source='www.nike.com',
        )]


def test_query_does_not_trust_weak_qwen_identifier():
    vision = {
        'marque': 'Nike',
        'objet': 'chaussure de sport',
        'modele_candidate': 'P-1000',
        'caracteristiques': ['argenté brillant', 'lacets', 'semelle épaisse'],
    }
    queries = build_queries(vision, ['SD attr', 'aaa ag', 'P-1000'])
    assert not any('P-1000' in q for q in queries)
    assert any('Nike' in q for q in queries)


def test_external_candidate_extraction():
    provider = FakeProvider()
    result = search_external(
        {
            'marque': 'Nike',
            'objet': 'chaussure de sport',
            'modele_candidate': 'P-1000',
            'caracteristiques': ['argenté brillant', 'lacets', 'semelle épaisse'],
        },
        ['SD attr', 'aaa ag'],
        provider=provider,
    )
    assert result['statut'] == 'ok'
    assert result['candidats']
    assert result['candidats'][0]['modele'] == 'P-6000'
    assert any('nike.com' in u for u in result['candidats'][0]['urls'])


if __name__ == '__main__':
    test_query_does_not_trust_weak_qwen_identifier()
    test_external_candidate_extraction()
    print('OK: V2.4 external search tests')
