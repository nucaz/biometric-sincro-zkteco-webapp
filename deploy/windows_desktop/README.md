# Empaquetado de la app de escritorio (Windows)

Convierte `attendance_gui.py` en un instalador Windows real
(`ZKTecoAttendanceSystem_Setup_X.Y.Z.0.exe`): compilado, con acceso
directo, entrada en "Agregar o quitar programas" y desinstalador.

## Requisitos (una sola vez, en la máquina donde compilas)

```powershell
# Dentro del venv del proyecto:
pip install pyinstaller
```

Además, [Inno Setup 6](https://jrsoftware.org/isdl.php) (gratuito) — ya
quedó instalado en esta máquina durante esta sesión.

## Generar una nueva versión

1. Edita `VERSION` en la raíz del proyecto (ej. `1.0.1`).
2. Corre:
   ```powershell
   .\deploy\windows_desktop\build.ps1
   ```
3. El instalador queda en `dist_installer\ZKTecoAttendanceSystem_Setup_1.0.1.0.exe`.

Ese `.exe` es lo único que se distribuye a los usuarios finales. Nunca se
les entrega el código fuente ni el `venv`.

## Qué tan "cerrado" queda -- honestamente

- El `.exe` que genera PyInstaller empaqueta el código Python ya
  compilado a bytecode dentro de un archivo binario. Un usuario normal
  **no puede abrirlo con un editor de texto y modificarlo** como haría
  con un `.py` -- necesita herramientas de ingeniería inversa
  específicas para extraer y entender el contenido.
- Esto **no es lo mismo que una protección DRM real**: alguien con
  conocimiento técnico y las herramientas correctas (ej. `pyinstxtractor`)
  puede extraer el bytecode y, con más esfuerzo, decompilarlo. Para la
  gran mayoría de usuarios de una empresa esto es más que suficiente
  ("cerrado" en el sentido práctico de "no editable por accidente ni por
  curiosidad"), pero no lo presentes como inviolable.
- Lo que sí es sólido: la única forma de generar una versión que
  reemplace la instalada es corriendo `build.ps1` desde el código fuente
  real -- nadie puede "parchear" el `.exe` instalado y que seguirlo
  pareciendo una actualización oficial sin volver a pasar por ese script
  (el instalador está firmado con la versión que viene de `VERSION`, y el
  próximo instalador con versión mayor simplemente reemplaza los archivos
  en `{app}`).

## Actualizar una instalación existente

Corriendo el instalador de una versión más nueva sobre una máquina que
ya tiene una versión instalada, Inno Setup la actualiza en el mismo
lugar (mismo `AppId`) sin duplicar accesos directos ni pedir desinstalar
primero. `devices.json` (la lista de relojes guardados) nunca se
sobreescribe ni se borra al desinstalar -- es dato del usuario, no del
programa.

## Archivos de este directorio

- `attendance_gui.spec` -- config de PyInstaller (qué archivos incluir).
- `version_info.txt` -- generado automáticamente por `build.ps1`, no lo
  edites a mano (se sobreescribe en cada build).
- `installer.iss` -- script de Inno Setup.
- `devices.default.json` -- lista de dispositivos vacía que se
  distribuye con el instalador (nunca el `devices.json` real del
  desarrollador, que tiene IPs reales de producción).
- `build.ps1` -- automatiza los tres pasos de arriba.
