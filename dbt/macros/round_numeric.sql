{#
    round_numeric(expr, places)
    Dialect shim: Postgres only defines round(numeric, int), DuckDB only
    round(double, int). Dispatch on adapter so both engines get a two-argument
    round, and cast the result back to double precision so the column type is
    identical on both engines (mart contracts depend on that parity).
#}
{% macro round_numeric(expr, places = 2) -%}
    {{ return(adapter.dispatch('round_numeric')(expr, places)) }}
{%- endmacro %}

{% macro default__round_numeric(expr, places) -%}
    cast(round({{ expr }}, {{ places }}) as double precision)
{%- endmacro %}

{% macro postgres__round_numeric(expr, places) -%}
    cast(round(({{ expr }})::numeric, {{ places }}) as double precision)
{%- endmacro %}
