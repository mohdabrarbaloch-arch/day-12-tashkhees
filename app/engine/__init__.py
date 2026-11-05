"""Tashkhees imaging engine.

A deterministic, explainable chest-radiograph measurement pipeline. Every stage
is a pure function over NumPy arrays, so the whole thing is unit-testable
without a network, a GPU, or a trained model file.

The design goal is *auditability*: a reviewer should be able to read the code
and reproduce every number the report shows.

Modules
-------
``imaging``
    Pure image primitives — loading, contrast normalisation, quality metrics,
    body/lung segmentation, and the radiographic measurements themselves.
``analyze``
    Orchestration. Turns measurements into findings by comparing them against
    published reference ranges, and computes a confidence for each.
``report``
    Composes a structured, radiology-style report from the findings.

This package deliberately does not re-export its submodules: ``analyze`` imports
``imaging``, so importing them here would create a partially-initialised package
during ``import app.engine``. Import the submodule you need directly.
"""
