import urllib.request
import re
import json

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

    # Create a list of dictionaries to store the book data
    books_data = []
    for i in range(min(5, len(titles))):
        books_data.append({
            "title": titles[i],
            "price": prices[i]
        })

    # Write the list of dictionaries to a JSON file with indentation
    with open('books_data.json', 'w') as json_file:
        json.dump(books_data, json_file, indent=4)

if __name__ == '__main__':
    url = 'http://books.toscrape.com/'
    scrape_books(url)
