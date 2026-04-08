import os
from dotenv import load_dotenv

load_dotenv()

# Mapbox Configuration
MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN")



REQUEST_DELAY_SECONDS = 1.5

# Output Configuration
DEFAULT_OUTPUT_DIR = "output/"

# Scoring Constants
LAMBDA_DECAY = 5.0 / 500.0  # e^-λd where λ = 5/500 for decay at 500m
