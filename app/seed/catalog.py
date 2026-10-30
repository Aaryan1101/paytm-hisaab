"""Static demo catalogue: item pools per supplier category and supplier name lists.

Item tuple: (description, hsn, gst_rate_percent, unit, base_rate). Rates follow app.engine.hsn_rates.
"""
ITEMS: dict[str, list[tuple[str, str, float, str, float]]] = {
    "staples": [("Basmati Rice 5kg", "1006", 5, "bag", 420.0), ("Atta 10kg", "1101", 5, "bag", 430.0),
                ("Sugar 1kg", "1701", 5, "kg", 44.0), ("Tea 250g", "0902", 5, "pkt", 120.0)],
    "dairy": [("Milk 1L", "0401", 0, "pkt", 56.0), ("Ghee 1kg", "0405", 5, "tin", 620.0),
              ("Butter 500g", "0405", 5, "pkt", 280.0), ("Paneer 200g", "0406", 5, "pkt", 90.0)],
    "oil": [("Mustard Oil 1L", "1514", 5, "btl", 160.0), ("Soyabean Oil 1L", "1507", 5, "btl", 135.0),
            ("Sunflower Oil 1L", "1512", 5, "btl", 150.0)],
    "snacks": [("Namkeen 400g", "2106", 5, "pkt", 95.0), ("Biscuits Family Pack", "1905", 5, "pkt", 40.0),
               ("Chocolate Bar", "1806", 18, "pc", 25.0)],
    "cleaning": [("Detergent Powder 1kg", "3402", 18, "pkt", 110.0), ("Dish Wash Gel 500ml", "3402", 18, "btl", 95.0),
                 ("Phenyl 1L", "3402", 18, "btl", 85.0)],
    "personal_care": [("Soap 100g", "3401", 5, "pc", 38.0), ("Shampoo 340ml", "3305", 5, "btl", 190.0),
                      ("Toothpaste 150g", "3306", 5, "pc", 85.0)],
    "fmcg": [("Biscuits Family Pack", "1905", 5, "pkt", 40.0), ("Soap 100g", "3401", 5, "pc", 38.0),
             ("Tea 250g", "0902", 5, "pkt", 120.0), ("Toothpaste 150g", "3306", 5, "pc", 85.0),
             ("Atta 10kg", "1101", 5, "bag", 430.0), ("Sugar 1kg", "1701", 5, "kg", 44.0)],
}

# name, category, aliases, is_linked_distributor
RAMESH_SUPPLIERS: list[tuple[str, str, tuple[str, ...], bool]] = [
    ("Sharma Traders", "fmcg", ("Sharma", "Sharma Trader"), True),
    ("Agarwal Dairy", "dairy", ("Agarwal", "Agarwal Diary"), False),
    ("Gupta Oil Mills", "oil", ("Gupta Oil",), False),
    ("Verma Snacks", "snacks", ("Verma",), False),
    ("Singh Rice Co", "staples", ("Singh Rice",), False),
    ("Jain Cleaning Supplies", "cleaning", ("Jain Cleaning",), False),
    ("Mishra Biscuits", "snacks", ("Mishra",), False),
    ("Tiwari Tea House", "staples", ("Tiwari Tea",), False),
    ("Khanna Sugar Depot", "staples", ("Khanna",), False),
    ("Yadav Masala", "staples", ("Yadav",), False),
    ("Pandey Soap Depot", "personal_care", ("Pandey",), False),
    ("Kapoor Beverages", "snacks", ("Kapoor",), False),
]

NEHA_SUPPLIER_NAMES = [
    "Rastogi Wholesale", "Saxena Agencies", "Bajpai Enterprises", "Dubey Distributors", "Chauhan Traders",
    "Awasthi Foods", "Mehra Oils", "Srivastava Staples", "Pathak Dairy Products", "Shukla General Supply",
    "Trivedi Cleaning Co", "Kanpur Plastics", "Dixit Sugar Mills", "Bhatia Biscuits", "Arora Snacks",
    "Malhotra Personal Care", "Kohli Tea Co", "Sethi Rice Mills", "Ahuja Packaging", "Goyal Masala",
    "Bansal Wholesale Foods", "Tandon Beverages", "Khatri Oil Traders", "Mathur Dairy", "Seth Detergents",
]
NEHA_OUT_OF_STATE = {"Ahuja Packaging": "27", "Khatri Oil Traders": "07"}  # IGST suppliers
NEHA_CATEGORIES = ["staples", "oil", "dairy", "snacks", "cleaning", "personal_care", "fmcg"]

RETAILER_NAME_PARTS = (
    ["Shree", "Ganesh", "Laxmi", "Balaji", "Jai", "Maa", "Om", "Radhe", "Krishna", "Sai", "New", "Royal"],
    ["General Store", "Kirana", "Provision Store", "Mart", "Super Shop", "Departmental Store", "Traders"],
)

UP_TOWNS = ["Lucknow", "Kanpur", "Unnao", "Barabanki", "Sitapur", "Raebareli", "Hardoi", "Gonda", "Aminabad", "Chowk"]
