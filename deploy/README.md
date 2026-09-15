# Empaquetado y despliegue

| Carpeta | Qué produce | Probado en esta sesión |
|---|---|---|
| [`windows_desktop/`](windows_desktop/README.md) | `ZKTecoAttendanceSystem_Setup_X.Y.Z.0.exe` -- instalador de la app de escritorio (PyInstaller + Inno Setup) | Sí, de punta a punta: build, instalación silenciosa, registro en "Agregar o quitar programas", ejecución, desinstalación |
| [`linux_server/`](linux_server/README.md) | Servicio systemd del panel central + PostgreSQL, para Debian/Ubuntu | No -- sin servidor Linux disponible en esta sesión. Sintaxis validada, lógica revisada con cuidado |
| [`windows_server/`](windows_server/README.md) | El mismo panel central como Tareas Programadas de Windows, con SQLite o apuntando a una BD externa | Sí, de punta a punta salvo el registro final de las tareas (requiere sesión con privilegios de Administrador que esta sesión no tiene) |

## Regla de oro

Los usuarios finales **nunca** reciben el código fuente ni un `venv` --
solo el instalador (`windows_desktop`) o el servicio ya corriendo
(`linux_server` / `windows_server`). La única forma de sacar una versión
nueva es editar el código fuente y volver a correr el script de build
correspondiente. `VERSION` en la raíz del proyecto controla el número de
versión del instalador de escritorio.
