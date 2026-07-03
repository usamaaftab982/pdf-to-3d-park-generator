# AI-work-Case-1-AI-Assisted-3D-Visualization-for-landscape-planning

**Note:** This project is not finished and some features are incomplete.

## Description

A prototype tool that converts 2D green construction plans to 3D representation in Blender.

## Project overview

Goal is to make design discussions, option comparisons and customer communication easier with the stakeholders with 3D rendering rather than relying only on 2D plan drawings.

## What it does

Pipeline includes 4 steps:

1. Extracting surfaces, vectors, and equipment from plan PDF to structured JSON file.
2. Enriching detected surface colors and areas for more realistic material types using LLM (Gemini)
3. Generating a 3D Blender scene from the JSON file
4. Rendering a preview image

Output:
- park_output.json (structured plan data)
- park_scene.blend (3D scene from the 2D plan)

## Technologies used

- Python
    - PyMuPDF (fitz) for the PDF vector, fill and text extraction and converting to JSON
    - Tkinter for GUI to run the pipeline
    - python-dotenv for loading .env variables
    - google-genai (Gemini API, model: gemini-3-flash-preview) for enriching the material
- Blender (bpy) for generating 3D scene from JSON file.
- Data format: JSON for structured text, blend for 3d Blender file

## Installation instructions

- Python 3.10+?
- Bender 5.0
- Gemini API key

Install dependencies:
pip install -r requirements.txt

Environment variables:
Create .env file in the repository root with API key:
GEMINI_API_KEY=YOUR_KEY_HERE

## Usage guide

Project can be run via UI with following steps:

1. Start the UI from the terminal: python UI.py
2. In the UI:
    - Click Browse PDF for selecting plan PDF (included in test folder)
    - Set Blender Executable path. If Blender is in PATH, keep blender, otherwise set full path
    - Select which steps to run:
        - Step 1: Extract PDF data creates structured JSON file park_output.json
        - Step 2: AI Material Enrichment adds material type to surfaces
        - Step 3: Generate 3D Model creates 3D model park_scene.blend
        - Step 4: Show Preview Image renders and opens model_preview.png
3. Click RUN PROCESS for creating 3D model. Log Output shows progression of the process.

Outputs from the process:
    - park_output.json
    - park_scene.blend
    - model_preview.png

## Team contribution

This project required a lot of reasearch work both for us to dive into the world of 3D and testing different models for possible solutions.

The work regarding research and testing was divided pretty equally with a small majority to Saku.
In addition there was the implementation part in terms of code, instructions and documentation. Most of the code implementation pushed into git was done by Lassi and Saku had more input on the documentation side.

So overall the team contribution was roughly:
 - Lassi: Research, testing, documentation and Code
 - Saku: Research, testing and documentation
