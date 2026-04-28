"""
AWS Lambda handler wrapping the FastAPI app via Mangum.
Deployed behind API Gateway (HTTP API or REST API).

The SAM template (template.yaml) wires this up automatically.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mangum import Mangum
from api import app

handler = Mangum(app, lifespan="off")
