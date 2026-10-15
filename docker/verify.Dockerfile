FROM base
USER root
RUN pip install --no-cache-dir pytest
COPY tests /checks/tests
USER researcher
WORKDIR /checks
CMD ["python", "-m", "pytest", "-q", "-rA", "tests/test_postgres_integration.py", "tests/test_container_runtime.py"]
