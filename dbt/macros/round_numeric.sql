{#
    round_numeric(expr, places)
    Dialect shim: Postgres only defines round(numeric, int), DuckDB only
    round(double, int). Dispatch on adapter so both engines get a two-argument
    round without per-model casts.
#}
{% macro round_numeric(expr, places = 2) -%}
    {{ return(adapter.dispatch('round_numeric')(expr, places)) }}
{%- endmacro %}

{% macro default__round_numeric(expr, places) -%}
    round({{ expr }}, {{ places }})
{%- endmacro %}

{% macro postgres__round_numeric(expr, places) -%}
    round(({{ expr }})::numeric, {{ places }})
{%- endmacro %}
