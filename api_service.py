from fastapi import FastAPI, Request
from pydantic import BaseModel
import urllib.request
import re
import json

app = FastAPI()

class ScrapeRequest(BaseModel):
    url: str = "http://books.toscrape.com/"

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "hello"}

@app.post("/scrape")
async def scrape_books(request: Request):
    # Get the payload from the request body, default to None
    payload = await request.json()
    url = payload.get('url', 'http://books.toscrape.com/')

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

    # Return the list of dictionaries as a JSON response
    return {"books": books_data}
