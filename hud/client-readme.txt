FRONTIER HUD PANEL
==================

A small panel (up to three lines with weapon and item icons) that Frontier servers fill:
Gun Game progress, item timers, next matches in the lobby. Without this file the same
information comes as a short message in the centre of the screen.

INSTALL
-------
1. Close Quake Live.
2. Open the Quake Live game folder:
   <Steam>\steamapps\common\Quake Live\
   (it has a "baseq3" folder with pak00.pk3 in it).
3. Unpack this archive there, so that this file ends up in place:
   Quake Live\baseq3\zz_modhud.pk3
   If you put our older files into your profile (<long number>\baseq3\ui\intro.menu and
   <long number>\baseq3\fonts\droidsansfallbackfull.ttf), delete them.
4. Start Quake Live. The panel only shows on servers that use it.

UPDATES: Frontier servers check that your zz_modhud.pk3 is the current one. If a server
refuses you with "Unpure client detected", download this archive again and replace the file.
Other pure servers that do not know this file may refuse you the same way: remove
zz_modhud.pk3 to play there.

UNINSTALL: delete Quake Live\baseq3\zz_modhud.pk3 and restart the game.

PANEL POSITION (your console, ~ key)
------------------------------------
seta mod_hud_pos top          top centre (default, also when not set)
seta mod_hud_pos center       just above the crosshair
seta mod_hud_pos bottom       bottom centre
seta mod_hud_pos left         left side, middle
seta mod_hud_pos topleft
seta mod_hud_pos bottomleft
seta mod_hud_pos right        right side, middle
seta mod_hud_pos topright
seta mod_hud_pos bottomright
seta mod_hud_pos off          hide the panel

Binds, for example:
bind F7 "seta mod_hud_pos off"
bind F8 "seta mod_hud_pos top"


ПАНЕЛЬ FRONTIER
===============

Небольшая плашка (до трёх строк с иконками оружия и предметов), которую заполняют серверы
Frontier: прогресс Gun Game, таймеры предметов, следующие матчи в лобби. Без этого файла та
же информация приходит короткой надписью по центру экрана.

УСТАНОВКА
---------
1. Закройте Quake Live.
2. Откройте папку игры Quake Live:
   <Steam>\steamapps\common\Quake Live\
   (в ней есть папка "baseq3" с файлом pak00.pk3).
3. Распакуйте архив туда, чтобы на месте оказался файл:
   Quake Live\baseq3\zz_modhud.pk3
   Если раньше вы клали наши файлы в профиль (<длинное число>\baseq3\ui\intro.menu и
   <длинное число>\baseq3\fonts\droidsansfallbackfull.ttf), удалите их.
4. Запустите Quake Live. Плашка появляется только на серверах, которые её используют.

ОБНОВЛЕНИЯ: серверы Frontier проверяют, что ваш zz_modhud.pk3 - текущей версии. Если сервер
не пускает с сообщением "Unpure client detected", скачайте архив заново и замените файл.
Чужие "чистые" (pure) серверы, которые не знают этот файл, могут не пустить так же:
чтобы играть там, уберите zz_modhud.pk3.

УДАЛЕНИЕ: удалите Quake Live\baseq3\zz_modhud.pk3 и перезапустите игру.

ПОЛОЖЕНИЕ ПЛАШКИ (в консоли, клавиша ~)
---------------------------------------
seta mod_hud_pos top          сверху по центру (по умолчанию, и когда не задано)
seta mod_hud_pos center       над прицелом
seta mod_hud_pos bottom       снизу по центру
seta mod_hud_pos left         слева посередине
seta mod_hud_pos topleft      слева сверху
seta mod_hud_pos bottomleft   слева снизу
seta mod_hud_pos right        справа посередине
seta mod_hud_pos topright     справа сверху
seta mod_hud_pos bottomright  справа снизу
seta mod_hud_pos off          скрыть плашку

Бинды, например:
bind F7 "seta mod_hud_pos off"
bind F8 "seta mod_hud_pos top"
