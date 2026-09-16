# Apify's Python base image, as in the official python-empty template.
FROM apify/actor-python:3.14

USER myuser

# Dependencies first, so a code-only change rebuilds quickly.
COPY --chown=myuser:myuser requirements.txt ./

RUN echo "Python version:" \
 && python --version \
 && echo "Pip version:" \
 && pip --version \
 && echo "Installing dependencies:" \
 && pip install -r requirements.txt \
 && echo "All installed Python packages:" \
 && pip freeze

COPY --chown=myuser:myuser . ./

RUN python -m compileall -q vetagent_actor/

CMD ["python", "-m", "vetagent_actor"]
