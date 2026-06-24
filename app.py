import os
import tempfile
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from gtm_pipeline_lib import build_insights
from render_pdf_lib import render_pdf

app = FastAPI(title="Chargeflow GTM Insights Pipeline")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-brief")
async def generate_brief(
    client_name: str = Form(...),
    dispute_reasons_classifier: UploadFile = File(...),
    prospect_dispute_data: UploadFile = File(...),
    prospect_responded_disputes: UploadFile = File(...),
):
    """
    Accepts the 3 raw prospect files (matching the n8n Form Trigger field
    names: dispute_reasons_classifier, prospect_dispute_data,
    prospect_responded_disputes) plus a client_name string, runs the
    DuckDB/pandas cleaning + analysis pipeline, renders the one-page PDF
    sales brief, and returns it as a downloadable file. The temp working
    directory is removed automatically once the response has been sent.
    """
    work_dir = tempfile.mkdtemp(prefix="gtm_brief_")

    def save_upload(upload: UploadFile) -> str:
        ext = os.path.splitext(upload.filename or "")[1].lower()
        if ext not in (".csv", ".xls", ".xlsx"):
            raise HTTPException(400, f"Unsupported file type for {upload.filename}: {ext}")
        dest = os.path.join(work_dir, f"{uuid.uuid4().hex}{ext}")
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        return dest

    try:
        classifier_path = save_upload(dispute_reasons_classifier)
        dispute_data_path = save_upload(prospect_dispute_data)
        responded_path = save_upload(prospect_responded_disputes)

        insights = build_insights(
            dispute_reasons_classifier_path=classifier_path,
            prospect_dispute_data_path=dispute_data_path,
            prospect_responded_disputes_path=responded_path,
            client_name=client_name,
        )

        output_pdf_path = os.path.join(work_dir, "gtm_insights_brief.pdf")
        render_pdf(insights, output_pdf_path)

        safe_name = "".join(c if c.isalnum() else "_" for c in client_name).strip("_") or "client"
        download_name = f"gtm_insights_brief_{safe_name}.pdf"

        return FileResponse(
            output_pdf_path,
            media_type="application/pdf",
            filename=download_name,
            background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except AssertionError as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(422, f"Data validation failed: {e}")
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(500, f"Pipeline failed: {e}")
