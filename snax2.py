import os
import sys
import time
import datetime
import requests
import re
import glob
from retry import retry
import pandas as pd
from bs4 import BeautifulSoup
from alive_progress import alive_bar
import targets   # this will be the template in published version
import lxml      # alt to html.parser, with cchardet >> speed up
import cchardet  # character recognition
import argparse


def args_setup():

    parser = argparse.ArgumentParser(description="Boots Product Scraper b21.05.05",
                                     epilog="Example: python3 snax2.py --links --products")
    parser.add_argument("--links",
                        action="store_true",
                        help="Just acquire the product links.")
    parser.add_argument("--products",
                        action="store_true",
                        help="Just acquire the product page detail fields.")

    args = parser.parse_args()

    return parser, args


def get_links_from_one_category(category, baseurl):

    """Get the full URL for each product in a category

    Args: a category and baseURL from snax_tagets
    Rets: a pandas series of the product URLs"""

    page_number = 1
    product_links = []
    page_string = "?pageNo=" #~ the URL page counter
    #~ the final section of the category URL
    category_name = category.split("/")[-1]

    with alive_bar(0, f"Acquiring product links for {category_name}") as bar:
        while True:
            #~ pull down the webpage
            target = requests.get(baseurl + category + page_string + str(page_number)).text
            #~ init BS object
            soup = BeautifulSoup(target, "lxml")
            #~ retrieve the link text element for all products on page
            product_list = soup.find_all("a", {"class": "product_name_link product_view_gtm"})
            #~ incrementing to an empty product page means we are done here
            if len(product_list) == 0:
                print(f"OK, {len(product_links)} {category_name} links retrieved [{page_number - 1} pages]")
                break
            #~ add to a list of the href URLs
            for product in product_list:
                link = product.get("href")
                product_links.append(link)
                bar() #~ increment progress bar
            #~ increment pagination
            page_number += 1

    #~ turn the list into a series and return
    linx = pd.Series(product_links)
    return linx


def make_dataframe_of_links_from_all_categories(start_time):

    """
    Rets: DF with first column as product URLs
    """

    all_links = pd.Series(dtype=str)
    print("\n" + f".oO Finding links for {len(targets.categories)} product categories")

    for category in targets.categories:
        product_links = get_links_from_one_category(category, targets.baseurl)
        all_links = all_links.append(product_links, ignore_index=True)

    all_links = all_links.drop_duplicates().reset_index(drop=True)
    #~ send series to DF
    all_links = all_links.to_frame()
    #~ label column one
    all_links.columns = ["product_link"]
    all_links.to_csv("output/linx_" + start_time + ".csv")

    return all_links



def populate_links_df_with_extracted_fields(dataframe, fields_to_extract, start_time):

    """Takes a dataframe where column 0 = URLs, generated by
    the get links function. Puts the contents of each
    field of interest into a dataframe.

    Args: dataframe column 0 = a URL,
          list of fields (a list of lists)
    Rets: populated dataframe"""

    total_snax = len(fields_to_extract) * dataframe.shape[0]
    regex = re.compile(r"[\n\r\t]+") #~ whitespace cleaner
    print("\n" + f".oO Requesting {total_snax} product details:")

    with alive_bar(total_snax,
                   f"""Acquiring {len(fields_to_extract)}
                   fields for {dataframe.shape[0]} products""") as bar:

        for index in range(dataframe.shape[0]):

            @retry(ConnectionResetError, tries=3, delay=10, backoff=10)
            def get_target_page(index):
                #~ pull down the full product page
                return requests.get(dataframe.at[index, "product_link"]).text

            target = get_target_page(index)

            #~ init BSoup object
            soup = BeautifulSoup(target, "lxml")

            for field in fields_to_extract:

                field_value = ""
                try:
                    if field[0] == "multi": #~ nested aquire from "Product details" div
                        try:
                            full_div = soup.find_all(field[1], attrs={field[2]: field[3]})
                            for i in full_div:
                                field_value += i.text.strip() + " "
                                field_value = regex.sub(" ", field_value)
                        except Exception as e:
                            print(f"Field \"{field[3]}\" not found", e)
                            continue
                    else: #~ just get the target field
                        field_value = soup.find(field[1], attrs={field[2]: field[3]}).get_text(strip=True)
                except AttributeError:
                    print(f"Field \"{field[3]}\" not found")
                    continue

                dataframe.loc[index, field[3]] = field_value
                bar()

    dataframe.to_csv("output/snax_" + start_time + ".csv")
    return dataframe


def select_long_description_field(dataframe):

    """Columns named 13 and 14 and called that because
    those are the nested div names on the boots website;
    it is unclear which will be the true field, so both are acquired.
    We need to take the longer field, the shorter always being PDF or
    ordering details, or other crap that we don't want."""

    with alive_bar(dataframe.shape[0],
                   f""".oO IDing long_description field for {dataframe.shape[0]} products""") as bar:

        for index in range(dataframe.shape[0]):

            #~ compare fields
            longer_field = max([dataframe.iloc[index]["13"]], [dataframe.iloc[index]["14"]])
            dataframe.loc[index, "long_description"] = longer_field
            bar()

    #~ remove candidate fields
    dataframe = dataframe.drop(["13", "14"], axis=1)

    return dataframe


def main():

    parser, args = args_setup()
    start_time = datetime.datetime.now().replace(microsecond=0).isoformat()

    print(f"\n.oO Starting snax2 @ {start_time} - target base URL is {targets.baseurl}")

    try:
        snax = make_dataframe_of_links_from_all_categories(start_time)
        snax = populate_links_df_with_extracted_fields(snax,
                                                       targets.fields_to_extract,
                                                       start_time)
        snax = select_long_description_field(snax)

    except KeyboardInterrupt:
        print("\n.oO OK, dropping. That run was not saved.")
        sys.exit(0)

    print(snax)


if __name__ == "__main__":

    main()

