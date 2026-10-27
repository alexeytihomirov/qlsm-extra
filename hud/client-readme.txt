FRONTIER HUD PANEL
==================

A small panel (up to three lines with weapon and item icons) that Frontier servers fill:
Gun Game progress, item timers, next matches in the lobby. Without these files the same
information comes as a short message in the centre of the screen.

INSTALL
-------
1. Close Quake Live.
2. Open your Quake Live profile folder:
   <Steam>\steamapps\common\Quake Live\<number>\
   (the long number is your Steam ID; that folder already has a "baseq3" folder with your config).
3. Unpack this archive there. These two files must end up in place:
   <number>\baseq3\ui\intro.menu
   <number>\baseq3\fonts\droidsansfallbackfull.ttf
   If you already have your own baseq3\ui\intro.menu (rare, some HUD packs ship one),
   keep a copy: ours replaces it.
4. Start Quake Live. Works on any server, pure ones included; the panel only shows on
   servers that use it.

UNINSTALL: delete the two files above and restart the game.

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

SERVER CHAT COMMANDS (admins of the server)
-------------------------------------------
!hud <1-3> <text>   set line 1, 2 or 3 of the panel for everyone
!hud clear          clear the panel
!hudicons           list every icon token with its icon (in chat)

Colours: ^1 red, ^2 green, ^3 yellow, ^4 blue, ^5 cyan, ^6 pink, ^7 white.
Icons are written as tokens in braces; {{ gives a plain "{".
Example: !hud 1 ^3{mh}^7 0:35  ^1{ra}^7 0:12

ICON TOKENS
-----------
@TOKENS@

Frame pieces can be typed as characters: ━ ┃ ┏ ┓ ┗ ┛ ┣ ┫ ╭ ╮ ╯ ╰


ПАНЕЛЬ FRONTIER
===============

Небольшая плашка (до трёх строк с иконками оружия и предметов), которую заполняют серверы
Frontier: прогресс Gun Game, таймеры предметов, следующие матчи в лобби. Без этих файлов та
же информация приходит короткой надписью по центру экрана.

УСТАНОВКА
---------
1. Закройте Quake Live.
2. Откройте папку своего профиля Quake Live:
   <Steam>\steamapps\common\Quake Live\<число>\
   (длинное число - ваш Steam ID; в этой папке уже есть папка "baseq3" с вашим конфигом).
3. Распакуйте архив туда. На месте должны оказаться два файла:
   <число>\baseq3\ui\intro.menu
   <число>\baseq3\fonts\droidsansfallbackfull.ttf
   Если у вас уже есть свой baseq3\ui\intro.menu (редко, его кладут некоторые HUD),
   сохраните копию: наш файл его заменит.
4. Запустите Quake Live. Работает на любых серверах, включая "чистые" (pure); плашка
   появляется только на серверах, которые её используют.

УДАЛЕНИЕ: удалите эти два файла и перезапустите игру.

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

КОМАНДЫ В ЧАТЕ СЕРВЕРА (для админов сервера)
--------------------------------------------
!hud <1-3> <текст>  строка 1, 2 или 3 плашки для всех
!hud clear          очистить плашку
!hudicons           список всех токенов иконок с самими иконками (в чат)

Цвета: ^1 красный, ^2 зелёный, ^3 жёлтый, ^4 синий, ^5 голубой, ^6 розовый, ^7 белый.
Иконки пишутся токенами в фигурных скобках; {{ даёт обычную "{".
Пример: !hud 1 ^3{mh}^7 0:35  ^1{ra}^7 0:12

Список токенов - в разделе ICON TOKENS выше.
