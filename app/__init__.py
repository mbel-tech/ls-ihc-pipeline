"""Desktop front end for the pipeline.

A real package rather than a namespace one, so `python -m app` finds
`app.__main__`. Without this file the launcher fails with "'app' is a package and
cannot be directly executed", which is exactly what run_app.bat invokes.
"""
