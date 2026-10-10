import urllib.request
import re

def scrape_books(url):
    # Fetch the content of the webpage
    response = urllib.request.urlopen(url)
    content = response.read().decode('utf-8')

    # Define the regex patterns to extract book titles and prices
    title_pattern = re.compile(r'<h3><a href=".*?">(.*?)</a></h3>')
    price_pattern = re.compile(r'<p class="price_color">£(.*?)</p>')

    # Find all matches for book titles and prices
    titles = title_pattern.findall(content)
    prices = price_pattern.findall(content)

    # Print the first 5 book titles and prices
    for i in range(min(5, len(titles))):
        print(f"Title: {titles[i]}")
        print(f"Price: £{prices[i]}")
        print("-" * 40)

if __name__ == '__main__':
    url = 'http://books.toscrape.com/'
    scrape_books(url)
