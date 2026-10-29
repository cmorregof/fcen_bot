"""Revisor de soportes para el cierre de un plan de mejoramiento.

Flujo:
1. `inventario`: recorre la carpeta del plan y asigna cada archivo a su acción
   por la ruta (determinista).
2. `describir`: el modelo describe cada archivo (qué es, fecha, qué prueba).
3. `cruce`: el modelo compara el indicador de cada acción con sus soportes y
   PROPONE un veredicto y un % de avance, con citas.
4. `verificador`: cada cita debe apuntar a un archivo del inventario
   (determinista). Lo que no cumple se marca, no se borra.
5. `salidas`: hojas y borrador para revisión humana.

El modelo no decide: todo lo que produce es una propuesta. La oficina de
calidad la revisa, el Comité Asesor recomienda aprobar o no aprobar el cierre y
el Consejo de Facultad decide.
"""
