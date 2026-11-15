"""Check that the fixed Soup Sieve and Beautiful Soup work together."""
import bs4
import soupsieve


def main():
    version = tuple(int(x) for x in soupsieve.__version__.split('.')[:2])
    if version < (4, 0):
        raise RuntimeError('Soup Sieve >=4.0 is required for security fixes')
    document = bs4.BeautifulSoup('<div class="test"><span>ok</span></div>', 'html.parser')
    assert len(document.select('div.test span')) == 1, 'CSS selector compatibility check failed'
    # This tiny pathological document triggered the known complexity issue.
    nested = bs4.BeautifulSoup('<div>' * 200, 'html.parser')
    assert not nested.select('section div div div')
    print(f'Soup Sieve {soupsieve.__version__}: selector compatibility check passed')


if __name__ == '__main__':
    main()
