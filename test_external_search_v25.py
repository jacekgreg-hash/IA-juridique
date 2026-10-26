from server.candidates.external import search_external
from server.candidates.web_search import WebResult


class FakeSearX:
    name = 'fake_searxng'
    enabled = True
    def search(self, query):
        return [WebResult(
            title='Nike P-6000 Metallic Silver',
            url='https://www.nike.com/fr/t/chaussure-nike-p-6000-Z6nJN4Ea',
            snippet='Nike P-6000 chaussure de sport Metallic Silver. Article CN0149-001.',
            source='fake_searxng',
        )]


class FakeBrave:
    name = 'fake_brave'
    enabled = True
    def search(self, query):
        raise AssertionError('Brave ne doit pas être appelé si SearXNG fournit des résultats')


def test_searxng_primary_brave_not_used():
    result = search_external(
        {'marque':'Nike','objet':'chaussure de sport','modele_candidate':'P-1000',
         'caracteristiques':['argenté brillant','lacets','semelle épaisse']},
        [], provider=FakeSearX(), fallback=FakeBrave()
    )
    assert result['statut'] == 'ok'
    assert result['providers_utilises'] == ['fake_searxng']
    assert result['candidats'][0]['modele'] == 'P-6000'


if __name__ == '__main__':
    test_searxng_primary_brave_not_used()
    print('OK: V2.5 SearXNG primary / Brave fallback')
