import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import pandas as pd
import numpy as np
from scipy.interpolate import SmoothBivariateSpline, LinearNDInterpolator, RBFInterpolator
from scipy.spatial import Delaunay
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.image as mpimg
import os
import traceback
import sys
import warnings
import ctypes

# Отключение автоматического масштабирования DPI для matplotlib
import matplotlib
matplotlib.use('TkAgg')  # Явно указываем бэкенд

# Настройка параметров matplotlib для избежания проблем с DPI
matplotlib.rcParams['figure.dpi'] = 100
matplotlib.rcParams['savefig.dpi'] = 100

#warnings.filterwarnings('ignore')

# Настройка DPI для Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

# Импорт Cartopy с дополнительными возможностями
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
    from cartopy.io import shapereader
    from cartopy.feature import ShapelyFeature
    CARTOPY_AVAILABLE = True
except ImportError:
    CARTOPY_AVAILABLE = False
    print("Cartopy не установлен. Будет использоваться базовая карта.")
    print("Для установки: pip install cartopy")

class ToolTip:
    """Класс для создания всплывающих подсказок"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.tip_visible = False
        self.after_id = None
        widget.bind('<Enter>', self.on_enter)
        widget.bind('<Leave>', self.on_leave)
        widget.bind('<ButtonPress>', self.on_click)

    def on_enter(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
        self.after_id = self.widget.after(300, self.show_tip)

    def on_leave(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        self.hide_tip()

    def on_click(self, event=None):
        self.hide_tip()

    def show_tip(self, event=None):
        if self.tip_visible:
            return

        try:
            x, y, _, _ = self.widget.bbox("insert")
            x += self.widget.winfo_rootx() + 25
            y += self.widget.winfo_rooty() + 25

            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")

            tw.transient(self.widget)

            label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                            font=("Arial", 10, "normal"), padx=5, pady=5)
            label.pack()

            tw.after(5000, self.hide_tip)
            self.tip_visible = True
        except Exception:
            pass

    def hide_tip(self, event=None):
        self.tip_visible = False
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except:
                pass
            self.tip_window = None

class CustomToolbar(NavigationToolbar2Tk):
    """Кастомная панель инструментов для размещения в верхней части окна"""
    def __init__(self, canvas, parent, app):
        self.app = app
        super().__init__(canvas, parent)

    def _init_toolbar(self):
        # Очищаем стандартные кнопки
        for child in self.winfo_children():
            child.destroy()

        # Создаем кнопки инструментов в горизонтальном порядке
        buttons = [
            ('Home', 'Домой', 'Восстановить исходный вид'),
            ('Back', 'Назад', 'Предыдущий вид'),
            ('Forward', 'Вперед', 'Следующий вид'),
            (None, None, None),  # Разделитель
            ('Pan', 'Панорамирование', 'Перемещение по графику'),
            ('Zoom', 'Масштаб', 'Масштабирование прямоугольником'),
            (None, None, None),  # Разделитель
            ('Save', 'Сохранить', 'Сохранить график')
        ]

        for btn_id, text, tooltip in buttons:
            if btn_id is None:
                ttk.Separator(self, orient='vertical').pack(side=tk.LEFT, padx=2, fill=tk.Y)
                continue

            btn = ttk.Button(self, text=text, width=12,
                           command=lambda x=btn_id: self._handle_tool(x))
            btn.pack(side=tk.LEFT, padx=2)
            ToolTip(btn, tooltip)

            # Сохраняем ссылки на кнопки
            if btn_id == 'Home':
                self.home_btn = btn
            elif btn_id == 'Back':
                self.back_btn = btn
            elif btn_id == 'Forward':
                self.forward_btn = btn
            elif btn_id == 'Pan':
                self.pan_btn = btn
            elif btn_id == 'Zoom':
                self.zoom_btn = btn
            elif btn_id == 'Save':
                self.save_btn = btn

        # Изначально отключаем кнопки навигации
        self.back_btn.config(state=tk.DISABLED)
        self.forward_btn.config(state=tk.DISABLED)

    def _handle_tool(self, tool):
        """Обработчик нажатия кнопок инструментов"""
        if tool == 'Home':
            self.home()
        elif tool == 'Back':
            self.back()
        elif tool == 'Forward':
            self.forward()
        elif tool == 'Pan':
            self.pan()
        elif tool == 'Zoom':
            self.zoom()
        elif tool == 'Save':
            self.save_figure()

    def save_figure(self):
        """Сохранение графика через приложение"""
        if self.app:
            self.app.save_plot()

    def set_message(self, s):
        """Переопределяем метод set_message"""
        if hasattr(self.app, 'status_var'):
            self.app.status_var.set(s)

class GeoInterpolationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Интерполяция геоданных с картой")

        # Получаем DPI масштабирование с обработкой ошибок
        try:
            self.dpi_scale = self.get_dpi_scale()
        except:
            self.dpi_scale = 1.0

        # Устанавливаем размер окна (используем фиксированные размеры для избежания проблем)
        base_width = 1400
        base_height = 850
        self.root.geometry(f"{base_width}x{base_height}")

        # Минимальный размер окна
        self.root.minsize(1200, 700)

        # Привязываем обработчик изменения размера окна
        self.root.bind('<Configure>', self.on_window_resize)

        # Переменные
        self.file_path = tk.StringVar()
        self.data = None
        self.param_columns = []
        self.selected_param = tk.StringVar()
        self.selected_method = tk.StringVar(value="IDW")
        self.grid_resolution = tk.StringVar(value="50")
        self.show_point_names = tk.BooleanVar(value=False)
        self.swap_coordinates = tk.BooleanVar(value=False)
        self.show_contours = tk.BooleanVar(value=False)
        self.contour_min = tk.StringVar(value="")
        self.contour_max = tk.StringVar(value="")
        self.contour_step = tk.StringVar(value="")
        self.contour_levels = tk.StringVar(value="10")

        # Параметры для метеорологических методов
        self.barnes_passes = tk.IntVar(value=3)
        self.barnes_gamma = tk.DoubleVar(value=0.5)
        self.cressman_radius = tk.DoubleVar(value=100.0)
        self.cressman_passes = tk.IntVar(value=3)
        self.cressman_radius_factor = tk.DoubleVar(value=0.7)

        # Переменные для карты и прозрачности
        self.show_map = tk.BooleanVar(value=False)
        self.map_type = tk.StringVar(value="detailed")
        self.map_alpha = tk.DoubleVar(value=0.3)
        self.interp_alpha = tk.DoubleVar(value=0.7)
        self.map_resolution = tk.StringVar(value="50m")
        self.show_country_borders = tk.BooleanVar(value=True)
        self.show_admin_borders = tk.BooleanVar(value=False)
        self.show_rivers = tk.BooleanVar(value=False)
        self.show_lakes = tk.BooleanVar(value=False)
        self.show_roads = tk.BooleanVar(value=False)
        self.map_zoom_level = tk.IntVar(value=5)

        # Переменные для цветовой палитры
        self.color_palette = tk.StringVar(value="viridis")
        self.reverse_palette = tk.BooleanVar(value=False)
        self.n_colors = tk.IntVar(value=20)

        # Инициализируем переменные для карт
        self.base_map = None
        self.user_map = None
        self.map_image = None
        self.map_extent = None

        # Переменная для скрытия левой панели
        self.left_panel_visible = tk.BooleanVar(value=True)

        # Переменная для отображения информации о методах
        self.show_method_info = tk.BooleanVar(value=False)

        # Словарь с описаниями методов
        self.method_descriptions = {
            "IDW": {
                "name": "Метод обратных взвешенных расстояний",
                "short": "IDW - простой и быстрый метод",
                "description": "Значение в точке вычисляется как средневзвешенное значение соседних точек, где вес обратно пропорционален расстоянию в степени p (обычно p=2).",
                "example": "Температура воздуха, высота рельефа",
                "advantages": "• Быстрый и простой в реализации\n• Интуитивно понятный\n• Хорошо работает для равномерно распределенных данных",
                "disadvantages": "• Не учитывает пространственную структуру\n• Чувствителен к выбросам\n• Может создавать эффект 'бычьих глаз'"
            },
            "B-сплайн": {
                "name": "B-сплайн интерполяция",
                "short": "Гладкая интерполяция полиномами",
                "description": "Использует кусочно-полиномиальные функции для создания гладкой поверхности, проходящей через все точки.",
                "example": "Цифровые модели рельефа, гладкие поля",
                "advantages": "• Создает очень гладкие поверхности\n• Хорошо интерполирует тренды\n• Гибкость настройки степени сглаживания",
                "disadvantages": "• Требует много точек\n• Может осциллировать при резких изменениях\n• Сложность выбора параметров"
            },
            "TIN": {
                "name": "Триангуляция Делоне",
                "short": "Линейная интерполяция по треугольникам",
                "description": "Строит триангуляцию Делоне и выполняет линейную интерполяцию внутри каждого треугольника.",
                "example": "Геологические поверхности, разломы",
                "advantages": "• Сохраняет локальные особенности\n• Работает с любым распределением точек\n• Не требует настройки параметров",
                "disadvantages": "• Поверхность не гладкая (кусочно-линейная)\n• Проблемы экстраполяции\n• Чувствителен к качеству триангуляции"
            },
            "Барнс (Barnes)": {
                "name": "Барнс-интерполяция",
                "short": "Метеорологический метод с многопроходным уточнением",
                "description": "Многопроходный метод с гауссовыми весами. Первый проход создает грубое поле, последующие уточняют его по невязкам.",
                "example": "Температура, давление, влажность в метеорологии",
                "advantages": "• Стандарт в оперативной метеорологии\n• Учитывает пространственную корреляцию\n• Позволяет контролировать гладкость",
                "disadvantages": "• Требует настройки параметров\n• Вычислительно затратен\n• Чувствителен к выбору радиуса"
            },
            "Крессман (Cressman)": {
                "name": "Крессман-интерполяция",
                "short": "Метод последовательных приближений",
                "description": "Классический метод объективного анализа. Использует круговые области влияния с последовательным уменьшением радиуса.",
                "example": "Анализ полей ветра, осадков",
                "advantages": "• Исторически первый метод объективного анализа\n• Простая реализация\n• Хорошо работает с редкой сеткой станций",
                "disadvantages": "• Может создавать ступенчатые поля\n• Менее точен, чем современные методы\n• Требует подбора радиусов"
            }
        }

        # Создание интерфейса
        self.create_widgets()

        # Предупреждение если Cartopy не установлен
        if not CARTOPY_AVAILABLE:
            self.show_cartopy_warning()

    def get_dpi_scale(self):
        """Получает масштабирование DPI для текущего экрана"""
        try:
            import ctypes
            try:
                # Используем более безопасный способ получения DPI
                hwnd = self.root.winfo_id()
                # Получаем DPI с помощью GetDpiForWindow (Windows 10 и новее)
                if hasattr(ctypes.windll.user32, 'GetDpiForWindow'):
                    dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                    if dpi > 0:
                        scale = dpi / 96.0
                        return min(max(scale, 0.5), 2.0)  # Ограничиваем масштаб
            except:
                pass

            # Альтернативный метод через winfo_fpixels
            try:
                dpi = self.root.winfo_fpixels('1i')
                if dpi > 0:
                    scale = dpi / 96.0
                    return min(max(scale, 0.5), 2.0)
            except:
                pass

            return 1.0
        except:
            return 1.0

    def on_window_resize(self, event=None):
        """Обработчик изменения размера окна"""
        if hasattr(self, 'canvas') and self.canvas:
            try:
                # Обновляем только если окно не свернуто
                if self.root.winfo_width() > 10 and self.root.winfo_height() > 10:
                    self.canvas.draw_idle()
            except Exception as e:
                print(f"Ошибка при изменении размера: {e}")

    def safe_toolbar_update(self):
        """Безопасное обновление тулбара с обработкой ошибок"""
        if hasattr(self, 'toolbar') and self.toolbar is not None:
            try:
                self.toolbar.update()
            except Exception as e:
                print(f"Ошибка при обновлении тулбара: {e}")

    def show_cartopy_warning(self):
        """Показывает предупреждение об отсутствии Cartopy"""
        warning_text = """Cartopy не установлен!

Для качественных картографических подложек рекомендуется установить Cartopy:

pip install cartopy

Также потребуются системные зависимости:
sudo apt-get install libproj-dev proj-data proj-bin libgeos-dev
или для Windows:
conda install -c conda-forge cartopy

Сейчас будет использоваться упрощенная карта."""

        messagebox.showwarning("Cartopy не найден", warning_text)

    def create_widgets(self):
        # Основной контейнер
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== ВЕРХНЯЯ ПАНЕЛЬ ИНСТРУМЕНТОВ =====
        toolbar_frame = ttk.LabelFrame(main_container, text="🛠️ Панель инструментов", padding=5)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))

        # Кнопки управления
        btn_frame = ttk.Frame(toolbar_frame)
        btn_frame.pack(fill=tk.X)

        # Кнопка для скрытия/показа левой панели
        self.toggle_btn = ttk.Button(btn_frame,
                                     text="◀ Скрыть панель настроек",
                                     command=self.toggle_left_panel,
                                     width=20)
        self.toggle_btn.pack(side=tk.LEFT, padx=2)

        # Кнопка для показа/скрытия информации о методах
        self.info_btn = ttk.Button(btn_frame,
                                   text="ℹ О методах",
                                   command=self.toggle_method_info,
                                   width=15)
        self.info_btn.pack(side=tk.LEFT, padx=2)

        # Разделитель
        ttk.Separator(btn_frame, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=2)

        # Инструменты для работы с картой
        if CARTOPY_AVAILABLE:
            ttk.Label(btn_frame, text="🌍 Карта:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(5, 2))

            self.map_check = ttk.Checkbutton(btn_frame, text="Показать",
                                             variable=self.show_map,
                                             command=self.toggle_map)
            self.map_check.pack(side=tk.LEFT, padx=2)
            ToolTip(self.map_check, "Включить/выключить отображение карты")

            self.map_type_combo = ttk.Combobox(btn_frame, textvariable=self.map_type,
                                               values=["detailed", "physical", "political", "relief", "satellite"],
                                               state="readonly", width=14)
            self.map_type_combo.pack(side=tk.LEFT, padx=2)
            self.map_type_combo.bind('<<ComboboxSelected>>', self.on_map_type_change)
            ToolTip(self.map_type_combo, "Тип картографической подложки")

            self.map_res_combo = ttk.Combobox(btn_frame, textvariable=self.map_resolution,
                                              values=["110m", "50m", "10m"],
                                              state="readonly", width=8)
            self.map_res_combo.pack(side=tk.LEFT, padx=2)
            self.map_res_combo.bind('<<ComboboxSelected>>', self.on_map_resolution_change)
            ToolTip(self.map_res_combo, "Разрешение карты (10m - максимальное)")

            extent_btn = ttk.Button(btn_frame, text="🎯 По данным",
                                   command=self.set_map_extent_from_data,
                                   width=12)
            extent_btn.pack(side=tk.LEFT, padx=2)
            ToolTip(extent_btn, "Установить границы карты по данным")

        ttk.Label(btn_frame, text="Прозрачность карты:").pack(side=tk.LEFT, padx=(10, 2))
        self.map_alpha_scale = ttk.Scale(btn_frame, from_=0.0, to=1.0,
                                         variable=self.map_alpha, orient=tk.HORIZONTAL,
                                         command=self.on_alpha_change,
                                         length=80)
        self.map_alpha_scale.pack(side=tk.LEFT, padx=2)
        self.map_alpha_label = ttk.Label(btn_frame, text="0.3", width=4)
        self.map_alpha_label.pack(side=tk.LEFT, padx=2)

        ttk.Label(btn_frame, text="Интерполяция:").pack(side=tk.LEFT, padx=(10, 2))
        self.interp_alpha_scale = ttk.Scale(btn_frame, from_=0.0, to=1.0,
                                           variable=self.interp_alpha, orient=tk.HORIZONTAL,
                                           command=self.on_interp_alpha_change,
                                           length=80)
        self.interp_alpha_scale.pack(side=tk.LEFT, padx=2)
        self.interp_alpha_label = ttk.Label(btn_frame, text="0.7", width=4)
        self.interp_alpha_label.pack(side=tk.LEFT, padx=2)

        self.exit_btn = ttk.Button(btn_frame, text="✕ Выход",
                                  command=self.exit_program,
                                  width=10)
        self.exit_btn.pack(side=tk.RIGHT, padx=2)
        ToolTip(self.exit_btn, "Завершить работу программы")

        # ===== ОСНОВНОЙ КОНТЕЙНЕР =====
        content_frame = ttk.Frame(main_container)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Левая панель с прокруткой (настройки)
        self.left_canvas = tk.Canvas(content_frame, width=450,
                                    highlightthickness=0)
        self.left_canvas.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))

        self.left_scrollbar = ttk.Scrollbar(content_frame, orient=tk.VERTICAL,
                                           command=self.left_canvas.yview)
        self.left_scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        self.left_canvas.bind('<Configure>', lambda e: self.left_canvas.configure(
            scrollregion=self.left_canvas.bbox("all")))

        self.left_panel = ttk.Frame(self.left_canvas, width=430)
        self.left_canvas.create_window((0, 0), window=self.left_panel, anchor="nw",
                                      width=430)

        def on_mousewheel(event):
            self.left_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        self.left_canvas.bind_all("<MouseWheel>", on_mousewheel)

        self.info_panel = ttk.Frame(content_frame, width=400)
        self.info_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        self.info_panel.pack_forget()

        self.right_panel = ttk.Frame(content_frame)
        self.right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.create_right_panel_content()
        self.create_left_panel_content()
        self.create_info_panel()

        style = ttk.Style()
        style.configure("Accent.TButton", font=('Arial', 10, 'bold'))

    def create_info_panel(self):
        """Создает панель с информацией о методах"""
        title_label = ttk.Label(self.info_panel, text="О методах интерполяции",
                                font=('Arial', 12, 'bold'))
        title_label.pack(pady=(0, 10), padx=5)

        info_canvas = tk.Canvas(self.info_panel, width=380,
                               highlightthickness=0)
        info_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info_scrollbar = ttk.Scrollbar(self.info_panel, orient=tk.VERTICAL,
                                      command=info_canvas.yview)
        info_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        info_canvas.configure(yscrollcommand=info_scrollbar.set)
        info_canvas.bind('<Configure>', lambda e: info_canvas.configure(
            scrollregion=info_canvas.bbox("all")))

        info_frame = ttk.Frame(info_canvas, width=360)
        info_canvas.create_window((0, 0), window=info_frame, anchor="nw",
                                 width=360)

        methods_order = ["IDW", "B-сплайн", "TIN", "Барнс (Barnes)", "Крессман (Cressman)"]

        for method in methods_order:
            desc = self.method_descriptions[method]

            method_frame = ttk.LabelFrame(info_frame, text=f"{method} - {desc['name']}", padding=5)
            method_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

            ttk.Label(method_frame, text=desc['short'],
                     font=('Arial', 9, 'italic'), foreground='blue').pack(anchor=tk.W, pady=(0, 5))

            ttk.Label(method_frame, text=desc['description'],
                     wraplength=330, justify=tk.LEFT).pack(anchor=tk.W, pady=2)

            ttk.Label(method_frame, text=f"📊 Применение: {desc['example']}",
                     font=('Arial', 9), foreground='green').pack(anchor=tk.W, pady=2)

            adv_frame = ttk.Frame(method_frame)
            adv_frame.pack(fill=tk.X, pady=2)
            ttk.Label(adv_frame, text="✅ Преимущества:",
                     font=('Arial', 9, 'bold')).pack(anchor=tk.W)
            ttk.Label(adv_frame, text=desc['advantages'],
                     wraplength=320, justify=tk.LEFT).pack(anchor=tk.W, padx=(10, 0))

            disadv_frame = ttk.Frame(method_frame)
            disadv_frame.pack(fill=tk.X, pady=2)
            ttk.Label(disadv_frame, text="⚠️ Недостатки:",
                     font=('Arial', 9, 'bold')).pack(anchor=tk.W)
            ttk.Label(disadv_frame, text=desc['disadvantages'],
                     wraplength=320, justify=tk.LEFT).pack(anchor=tk.W, padx=(10, 0))

            ttk.Separator(method_frame, orient='horizontal').pack(fill=tk.X, pady=5)

        tips_frame = ttk.LabelFrame(info_frame, text="💡 Рекомендации по выбору метода", padding=5)
        tips_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        tips_text = """• IDW: быстрая оценка, равномерные данные
• B-сплайн: гладкие поверхности, цифровые модели рельефа
• TIN: локальные особенности, геологические данные
• Барнс: метеорологические поля, температура, давление
• Крессман: анализ ветра, осадков, редкая сеть станций"""

        ttk.Label(tips_frame, text=tips_text, wraplength=330,
                 justify=tk.LEFT).pack(pady=5)

        ttk.Label(info_frame, text="").pack(pady=10)

    def create_left_panel_content(self):
        """Создает содержимое левой панели настроек"""
        title_label = ttk.Label(self.left_panel, text="⚙️ Настройки интерполяции",
                                font=('Arial', 12, 'bold'))
        title_label.pack(pady=(0, 10), padx=5)

        file_frame = ttk.LabelFrame(self.left_panel, text="📁 Файл данных", padding=5)
        file_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        ttk.Button(file_frame, text="Выбрать файл", command=self.select_file).pack(fill=tk.X, pady=2)
        ToolTip(file_frame.winfo_children()[-1], "Выберите CSV или TXT файл с данными")

        ttk.Entry(file_frame, textvariable=self.file_path,
                 width=50).pack(fill=tk.X, pady=2)
        ToolTip(file_frame.winfo_children()[-1], "Путь к выбранному файлу")

        ttk.Button(file_frame, text="Загрузить", command=self.load_file).pack(fill=tk.X, pady=2)
        ToolTip(file_frame.winfo_children()[-1], "Загрузить данные из файла")

        params_frame = ttk.LabelFrame(self.left_panel, text="📊 Параметры интерполяции", padding=5)
        params_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        ttk.Label(params_frame, text="Параметр:").pack(anchor=tk.W, pady=(5, 2))
        self.param_combo = ttk.Combobox(params_frame, textvariable=self.selected_param,
                                       state="readonly", width=48)
        self.param_combo.pack(fill=tk.X, pady=(0, 5))
        self.param_combo.bind('<<ComboboxSelected>>', self.on_param_selected)
        ToolTip(self.param_combo, "Выберите числовой параметр для интерполяции")

        ttk.Label(params_frame, text="Метод интерполяции:").pack(anchor=tk.W, pady=(5, 2))

        method_select_frame = ttk.Frame(params_frame)
        method_select_frame.pack(fill=tk.X, pady=(0, 5))

        methods = ["IDW", "B-сплайн", "TIN (Triangulation)",
                  "Барнс (Barnes)", "Крессман (Cressman)"]
        method_combo = ttk.Combobox(method_select_frame, textvariable=self.selected_method,
                                   values=methods, state="readonly",
                                   width=40)
        method_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        method_combo.bind('<<ComboboxSelected>>', self.on_method_selected)
        ToolTip(method_combo, "Выберите метод интерполяции")

        info_btn = ttk.Button(method_select_frame, text="?", width=3,
                             command=self.show_current_method_info)
        info_btn.pack(side=tk.RIGHT, padx=(5, 0))
        ToolTip(info_btn, "Показать информацию о выбранном методе")

        ttk.Label(params_frame, text="Размер сетки (NxN):").pack(anchor=tk.W, pady=(5, 2))
        grid_entry = ttk.Entry(params_frame, textvariable=self.grid_resolution,
                              width=48)
        grid_entry.pack(fill=tk.X, pady=(0, 5))
        ToolTip(grid_entry, "Количество точек сетки (чем больше, тем детальнее, но медленнее)")

        # Настройки карты (расширенные)
        if CARTOPY_AVAILABLE:
            map_settings_frame = ttk.LabelFrame(self.left_panel, text="🗺️ Детальные настройки карты", padding=5)
            map_settings_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

            # Слои карты
            ttk.Label(map_settings_frame, text="Слои карты:", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))

            borders_check = ttk.Checkbutton(map_settings_frame, text="Границы государств",
                                           variable=self.show_country_borders,
                                           command=self.on_map_layer_change)
            borders_check.pack(anchor=tk.W, padx=(10, 0), pady=2)
            ToolTip(borders_check, "Показать границы государств")

            admin_check = ttk.Checkbutton(map_settings_frame, text="Административные границы",
                                         variable=self.show_admin_borders,
                                         command=self.on_map_layer_change)
            admin_check.pack(anchor=tk.W, padx=(10, 0), pady=2)
            ToolTip(admin_check, "Показать административные границы (области, штаты)")

            rivers_check = ttk.Checkbutton(map_settings_frame, text="Реки",
                                          variable=self.show_rivers,
                                          command=self.on_map_layer_change)
            rivers_check.pack(anchor=tk.W, padx=(10, 0), pady=2)
            ToolTip(rivers_check, "Показать реки")

            lakes_check = ttk.Checkbutton(map_settings_frame, text="Озера",
                                         variable=self.show_lakes,
                                         command=self.on_map_layer_change)
            lakes_check.pack(anchor=tk.W, padx=(10, 0), pady=2)
            ToolTip(lakes_check, "Показать озера")

            roads_check = ttk.Checkbutton(map_settings_frame, text="Дороги",
                                         variable=self.show_roads,
                                         command=self.on_map_layer_change)
            roads_check.pack(anchor=tk.W, padx=(10, 0), pady=2)
            ToolTip(roads_check, "Показать дороги (требуется загрузка данных)")

            # Качество рендеринга
            ttk.Label(map_settings_frame, text="", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))

            ttk.Label(map_settings_frame, text="Разрешение карты:").pack(anchor=tk.W, pady=(2, 2))
            res_frame = ttk.Frame(map_settings_frame)
            res_frame.pack(fill=tk.X, pady=2)
            res_110m = ttk.Radiobutton(res_frame, text="110m (низкое)", variable=self.map_resolution, value="110m",
                                      command=self.on_map_resolution_change)
            res_110m.pack(side=tk.LEFT, padx=5)
            res_50m = ttk.Radiobutton(res_frame, text="50m (среднее)", variable=self.map_resolution, value="50m",
                                     command=self.on_map_resolution_change)
            res_50m.pack(side=tk.LEFT, padx=5)
            res_10m = ttk.Radiobutton(res_frame, text="10m (высокое)", variable=self.map_resolution, value="10m",
                                     command=self.on_map_resolution_change)
            res_10m.pack(side=tk.LEFT, padx=5)
            ToolTip(res_10m, "10m - максимальное разрешение, требует загрузки данных")

        self.barnes_frame = ttk.LabelFrame(self.left_panel, text="📈 Параметры Барнс-интерполяции", padding=5)

        ttk.Label(self.barnes_frame, text="Количество проходов:").pack(anchor=tk.W, pady=(5, 2))
        barnes_passes_frame = ttk.Frame(self.barnes_frame)
        barnes_passes_frame.pack(fill=tk.X)
        barnes_scale = ttk.Scale(barnes_passes_frame, from_=1, to=10, variable=self.barnes_passes,
                 orient=tk.HORIZONTAL, command=self.on_barnes_passes_change,
                 length=200)
        barnes_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(barnes_scale, "Количество итераций уточнения поля (больше = точнее, но медленнее)")
        self.barnes_passes_label = ttk.Label(barnes_passes_frame, text="3", width=5)
        self.barnes_passes_label.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(self.barnes_frame, text="Параметр сглаживания γ:").pack(anchor=tk.W, pady=(5, 2))
        gamma_frame = ttk.Frame(self.barnes_frame)
        gamma_frame.pack(fill=tk.X)
        gamma_scale = ttk.Scale(gamma_frame, from_=0.1, to=1.0, variable=self.barnes_gamma,
                 orient=tk.HORIZONTAL, command=self.on_barnes_gamma_change,
                 length=200)
        gamma_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(gamma_scale, "γ > 0.5 - более гладкое поле, γ < 0.5 - ближе к данным")
        self.barnes_gamma_label = ttk.Label(gamma_frame, text="0.5", width=5)
        self.barnes_gamma_label.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(self.barnes_frame, text="γ > 0.5 - более гладкое поле\nγ < 0.5 - ближе к данным",
                 font=('Arial', 8), foreground='gray').pack(anchor=tk.W, pady=2)

        self.cressman_frame = ttk.LabelFrame(self.left_panel, text="📉 Параметры Крессман-интерполяции", padding=5)

        ttk.Label(self.cressman_frame, text="Начальный радиус (км):").pack(anchor=tk.W, pady=(5, 2))
        radius_frame = ttk.Frame(self.cressman_frame)
        radius_frame.pack(fill=tk.X)
        radius_scale = ttk.Scale(radius_frame, from_=10, to=500, variable=self.cressman_radius,
                 orient=tk.HORIZONTAL, command=self.on_cressman_radius_change,
                 length=200)
        radius_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(radius_scale, "Радиус влияния на первом проходе (должен быть больше max расстояния между станциями)")
        self.cressman_radius_label = ttk.Label(radius_frame, text="100.0", width=5)
        self.cressman_radius_label.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(self.cressman_frame, text="Количество проходов:").pack(anchor=tk.W, pady=(5, 2))
        passes_frame = ttk.Frame(self.cressman_frame)
        passes_frame.pack(fill=tk.X)
        passes_scale = ttk.Scale(passes_frame, from_=1, to=5, variable=self.cressman_passes,
                 orient=tk.HORIZONTAL, command=self.on_cressman_passes_change,
                 length=200)
        passes_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(passes_scale, "Количество итераций с уменьшающимся радиусом")
        self.cressman_passes_label = ttk.Label(passes_frame, text="3", width=5)
        self.cressman_passes_label.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(self.cressman_frame, text="Коэф. уменьшения радиуса:").pack(anchor=tk.W, pady=(5, 2))
        factor_frame = ttk.Frame(self.cressman_frame)
        factor_frame.pack(fill=tk.X)
        factor_scale = ttk.Scale(factor_frame, from_=0.3, to=0.9, variable=self.cressman_radius_factor,
                 orient=tk.HORIZONTAL, command=self.on_cressman_factor_change,
                 length=200)
        factor_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ToolTip(factor_scale, "Множитель уменьшения радиуса на каждом проходе (0.7 = уменьшение на 30%)")
        self.cressman_factor_label = ttk.Label(factor_frame, text="0.7", width=5)
        self.cressman_factor_label.pack(side=tk.RIGHT, padx=(5, 0))

        display_frame = ttk.LabelFrame(self.left_panel, text="🎨 Опции отображения", padding=5)
        display_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        names_check = ttk.Checkbutton(display_frame, text="Показывать названия точек",
                       variable=self.show_point_names,
                       command=self.toggle_point_names)
        names_check.pack(anchor=tk.W, pady=2)
        ToolTip(names_check, "Отображать названия точек на графике")

        swap_check = ttk.Checkbutton(display_frame, text="Поменять местами широту и долготу",
                       variable=self.swap_coordinates,
                       command=self.toggle_coordinates)
        swap_check.pack(anchor=tk.W, pady=2)
        ToolTip(swap_check, "Если координаты в файле перепутаны")

        contours_check = ttk.Checkbutton(display_frame, text="Показывать изолинии",
                       variable=self.show_contours,
                       command=self.toggle_contours)
        contours_check.pack(anchor=tk.W, pady=2)
        ToolTip(contours_check, "Отображать изолинии значений")

        # Фрейм для выбора цветовой палитры
        palette_frame = ttk.Frame(display_frame)
        palette_frame.pack(fill=tk.X, pady=5)

        ttk.Label(palette_frame, text="🎨 Цветовая палитра:",
                  font=('Arial', 9)).pack(anchor=tk.W, pady=(0, 2))

        palettes = [
            "viridis", "plasma", "inferno", "magma", "cividis",
            "coolwarm", "RdBu", "RdYlBu", "seismic",
            "jet", "rainbow", "hsv",
            "hot", "cool", "spring", "summer", "autumn", "winter",
            "terrain", "Spectral", "twilight", "gist_earth"
        ]

        self.palette_combo = ttk.Combobox(palette_frame, textvariable=self.color_palette,
                                         values=palettes, state="readonly",
                                         width=40)
        self.palette_combo.pack(fill=tk.X, pady=(0, 2))
        self.palette_combo.bind('<<ComboboxSelected>>', self.on_palette_change)
        ToolTip(self.palette_combo, "Выберите цветовую схему для интерполяции")

        palette_preview_btn = ttk.Button(palette_frame, text="Показать примеры",
                                        command=self.show_palette_preview,
                                        width=20)
        palette_preview_btn.pack(pady=(2, 0))
        ToolTip(palette_preview_btn, "Показать все доступные цветовые палитры")

        # Чекбокс для инверсии палитры
        reverse_check = ttk.Checkbutton(display_frame, text="Инвертировать палитру",
                                       variable=self.reverse_palette,
                                       command=self.on_reverse_palette_change)
        reverse_check.pack(anchor=tk.W, pady=2)
        ToolTip(reverse_check, "Перевернуть цветовую схему")

        # Настройка количества цветов
        colors_frame = ttk.Frame(display_frame)
        colors_frame.pack(fill=tk.X, pady=5)

        ttk.Label(colors_frame, text="Количество цветов:").pack(side=tk.LEFT, padx=(0, 5))
        colors_scale = ttk.Scale(colors_frame, from_=5, to=50, variable=self.n_colors,
                                orient=tk.HORIZONTAL, command=self.on_n_colors_change,
                                length=150)
        colors_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.n_colors_label = ttk.Label(colors_frame, text="20", width=4)
        self.n_colors_label.pack(side=tk.RIGHT, padx=(5, 0))
        ToolTip(colors_scale, "Количество цветовых уровней (больше = более плавный переход")

        # Настройки изолиний
        contours_frame = ttk.Frame(display_frame)
        contours_frame.pack(fill=tk.X, pady=5)

        min_frame = ttk.Frame(contours_frame)
        min_frame.pack(fill=tk.X, pady=1)
        ttk.Label(min_frame, text="Мин:", width=5).pack(side=tk.LEFT)
        min_entry = ttk.Entry(min_frame, textvariable=self.contour_min,
                             width=15)
        min_entry.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(min_entry, "Минимальное значение для изолиний")

        max_frame = ttk.Frame(contours_frame)
        max_frame.pack(fill=tk.X, pady=1)
        ttk.Label(max_frame, text="Макс:", width=5).pack(side=tk.LEFT)
        max_entry = ttk.Entry(max_frame, textvariable=self.contour_max,
                             width=15)
        max_entry.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(max_entry, "Максимальное значение для изолиний")

        step_frame = ttk.Frame(contours_frame)
        step_frame.pack(fill=tk.X, pady=1)
        ttk.Label(step_frame, text="Шаг:", width=5).pack(side=tk.LEFT)
        step_entry = ttk.Entry(step_frame, textvariable=self.contour_step,
                              width=15)
        step_entry.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(step_entry, "Шаг между изолиниями")

        levels_frame = ttk.Frame(contours_frame)
        levels_frame.pack(fill=tk.X, pady=1)
        ttk.Label(levels_frame, text="Уровней:", width=5).pack(side=tk.LEFT)
        levels_entry = ttk.Entry(levels_frame, textvariable=self.contour_levels,
                                width=15)
        levels_entry.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(levels_entry, "Количество уровней (если не заданы мин/макс/шаг)")

        auto_btn = ttk.Button(contours_frame, text="Авто", command=self.auto_contour_settings,
                             width=10)
        auto_btn.pack(fill=tk.X, pady=5)
        ToolTip(auto_btn, "Автоматически установить параметры изолиний по данным")

        actions_frame = ttk.LabelFrame(self.left_panel, text="▶️ Действия", padding=5)
        actions_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        self.execute_btn = ttk.Button(actions_frame, text="▶ Выполнить интерполяцию",
                                      command=self.perform_interpolation,
                                      style="Accent.TButton")
        self.execute_btn.pack(fill=tk.X, pady=2)
        ToolTip(self.execute_btn, "Запустить интерполяцию выбранным методом")

        self.update_plot_btn = ttk.Button(actions_frame, text="↻ Обновить отображение",
                                         command=self.update_plot,
                                         state="disabled")
        self.update_plot_btn.pack(fill=tk.X, pady=2)
        ToolTip(self.update_plot_btn, "Обновить график с новыми настройками")

        self.save_plot_btn = ttk.Button(actions_frame, text="💾 Сохранить график",
                                       command=self.save_plot,
                                       state="disabled")
        self.save_plot_btn.pack(fill=tk.X, pady=2)
        ToolTip(self.save_plot_btn, "Сохранить текущий график в файл")

        status_frame = ttk.LabelFrame(self.left_panel, text="📌 Статус", padding=5)
        status_frame.pack(fill=tk.X, pady=(10, 20), padx=5)

        self.status_var = tk.StringVar(value="Готов к работе")
        status_label = ttk.Label(status_frame, textvariable=self.status_var,
                                wraplength=410, justify=tk.LEFT)
        status_label.pack(fill=tk.X)

        ttk.Label(self.left_panel, text="").pack(pady=10)

    def create_right_panel_content(self):
        """Создает содержимое правой панели с графиком и инструментами"""
        # Верхняя панель с инструментами графика
        top_toolbar_frame = ttk.Frame(self.right_panel)
        top_toolbar_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))

        # Добавляем метку
        ttk.Label(top_toolbar_frame, text="🔧 Инструменты графика:",
                 font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)

        # Фрейм для графика
        plot_frame = ttk.LabelFrame(self.right_panel, text="🗺️ Результат интерполяции", padding=5)
        plot_frame.pack(fill=tk.BOTH, expand=True)

        # Используем безопасное значение DPI
        safe_dpi = 100

        self.figure = plt.Figure(figsize=(12, 9), dpi=safe_dpi)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Создаем кастомную панель инструментов и размещаем её в верхней панели
        self.toolbar = CustomToolbar(self.canvas, top_toolbar_frame, self)
        self.toolbar.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        self.last_results = None

    def toggle_method_info(self):
        """Показывает или скрывает панель с информацией о методах"""
        if self.show_method_info.get():
            self.info_panel.pack_forget()
            self.show_method_info.set(False)
            self.info_btn.config(text="ℹ О методах")
        else:
            self.info_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5), before=self.right_panel)
            self.show_method_info.set(True)
            self.info_btn.config(text="✕ Скрыть информацию")

    def show_current_method_info(self):
        """Показывает информацию о текущем выбранном методе"""
        method = self.selected_method.get()
        desc = self.method_descriptions.get(method, self.method_descriptions["IDW"])

        info_text = f"""Метод: {desc['name']}

{desc['description']}

📊 Применение: {desc['example']}

✅ Преимущества:
{desc['advantages']}

⚠️ Недостатки:
{desc['disadvantages']}"""

        messagebox.showinfo(f"О методе {method}", info_text)

    def toggle_left_panel(self):
        """Скрывает или показывает левую панель настроек"""
        if self.left_panel_visible.get():
            self.left_canvas.pack_forget()
            self.left_scrollbar.pack_forget()
            self.toggle_btn.config(text="▶ Показать настройки")
            self.left_panel_visible.set(False)
            self.status_var.set("Панель настроек скрыта")
        else:
            self.left_canvas.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
            self.left_scrollbar.pack(side=tk.LEFT, fill=tk.Y)
            self.toggle_btn.config(text="◀ Скрыть настройки")
            self.left_panel_visible.set(True)
            self.status_var.set("Панель настроек показана")

    def on_method_selected(self, event):
        """Обработчик выбора метода интерполяции"""
        method = self.selected_method.get()
        desc = self.method_descriptions.get(method, self.method_descriptions["IDW"])
        self.status_var.set(f"Выбран метод: {desc['name']}")

        self.barnes_frame.pack_forget()
        self.cressman_frame.pack_forget()

        if method == "Барнс (Barnes)":
            self.barnes_frame.pack(fill=tk.X, pady=(0, 10), padx=5, after=self.param_combo.master)
        elif method == "Крессман (Cressman)":
            self.cressman_frame.pack(fill=tk.X, pady=(0, 10), padx=5, after=self.param_combo.master)

    def on_map_type_change(self, event=None):
        """Обработчик изменения типа карты"""
        if self.last_results is not None:
            self.update_plot()

    def on_map_resolution_change(self, event=None):
        """Обработчик изменения разрешения карты"""
        if self.last_results is not None:
            self.update_plot()
            resolution = self.map_resolution.get()
            if resolution == "10m":
                self.status_var.set("Выбрано высокое разрешение (10m). Возможна загрузка данных...")

    def on_map_layer_change(self, event=None):
        """Обработчик изменения слоев карты"""
        if self.last_results is not None:
            self.update_plot()

    def set_map_extent_from_data(self):
        """Устанавливает границы карты по данным"""
        if self.data is not None:
            if self.swap_coordinates.get():
                x = self.data.iloc[:, 2].values.astype(float)
                y = self.data.iloc[:, 1].values.astype(float)
            else:
                x = self.data.iloc[:, 1].values.astype(float)
                y = self.data.iloc[:, 2].values.astype(float)

            x_min, x_max = x.min(), x.max()
            y_min, y_max = y.min(), y.max()

            x_pad = (x_max - x_min) * 0.1
            y_pad = (y_max - y_min) * 0.1

            self.map_extent = [x_min - x_pad, x_max + x_pad, y_min - y_pad, y_max + y_pad]
            self.status_var.set(f"Границы карты: {x_min:.2f}-{x_max:.2f}, {y_min:.2f}-{y_max:.2f}")

            if self.last_results is not None:
                self.update_plot()
        else:
            messagebox.showwarning("Предупреждение", "Сначала загрузите данные!")

    def on_barnes_passes_change(self, value):
        self.barnes_passes_label.config(text=str(int(float(value))))

    def on_barnes_gamma_change(self, value):
        self.barnes_gamma_label.config(text=f"{float(value):.1f}")

    def on_cressman_radius_change(self, value):
        self.cressman_radius_label.config(text=f"{float(value):.1f}")

    def on_cressman_passes_change(self, value):
        self.cressman_passes_label.config(text=str(int(float(value))))

    def on_cressman_factor_change(self, value):
        self.cressman_factor_label.config(text=f"{float(value):.1f}")

    def toggle_map(self):
        """Переключение отображения карты"""
        status = "включено" if self.show_map.get() else "отключено"
        self.status_var.set(f"Отображение карты {status}")
        if self.last_results is not None:
            self.update_plot()

    def on_alpha_change(self, value):
        """Изменение прозрачности карты"""
        alpha = float(value)
        self.map_alpha_label.config(text=f"{alpha:.1f}")
        if self.last_results is not None:
            self.update_plot()

    def on_interp_alpha_change(self, value):
        """Изменение прозрачности интерполяции"""
        alpha = float(value)
        self.interp_alpha_label.config(text=f"{alpha:.1f}")
        if self.last_results is not None:
            self.update_plot()

    def on_palette_change(self, event=None):
        """Обработчик изменения цветовой палитры"""
        palette = self.color_palette.get()
        self.status_var.set(f"Выбрана палитра: {palette}")
        if self.last_results is not None:
            self.update_plot()

    def on_reverse_palette_change(self):
        """Обработчик инверсии палитры"""
        if self.last_results is not None:
            self.update_plot()

    def on_n_colors_change(self, value):
        """Обработчик изменения количества цветов"""
        n = int(float(value))
        self.n_colors_label.config(text=str(n))
        if self.last_results is not None:
            self.update_plot()

    def show_palette_preview(self):
        """Показывает окно с примерами всех цветовых палитр"""
        preview_window = tk.Toplevel(self.root)
        preview_window.title("Цветовые палитры")
        preview_window.geometry("900x700")

        canvas = tk.Canvas(preview_window)
        scrollbar = ttk.Scrollbar(preview_window, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        palettes = [
            "viridis", "plasma", "inferno", "magma", "cividis",
            "coolwarm", "RdBu", "RdYlBu", "seismic",
            "jet", "rainbow", "hsv",
            "hot", "cool", "spring", "summer", "autumn", "winter",
            "terrain", "Spectral", "twilight", "gist_earth"
        ]

        for i, palette in enumerate(palettes):
            frame = ttk.LabelFrame(scrollable_frame, text=palette, padding=5)
            frame.pack(fill=tk.X, padx=10, pady=5)

            fig = plt.Figure(figsize=(8, 1), dpi=80)
            ax = fig.add_subplot(111)

            gradient = np.linspace(0, 1, 256).reshape(1, -1)

            im = ax.imshow(gradient, aspect='auto', cmap=palette)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(palette, fontsize=10)

            canvas_widget = FigureCanvasTkAgg(fig, master=frame)
            canvas_widget.draw()
            canvas_widget.get_tk_widget().pack(fill=tk.X)

            apply_btn = ttk.Button(frame, text="Применить",
                                  command=lambda p=palette: self.apply_palette_and_close(p, preview_window))
            apply_btn.pack(pady=5)

        ttk.Label(scrollable_frame, text="Нажмите 'Применить' для выбора палитры",
                 font=('Arial', 10, 'bold')).pack(pady=10)

    def apply_palette_and_close(self, palette, window):
        """Применяет выбранную палитру и закрывает окно предпросмотра"""
        self.color_palette.set(palette)
        self.on_palette_change()
        window.destroy()

    def select_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите файл данных",
            filetypes=[("CSV файлы", "*.csv"), ("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
        )
        if filename:
            self.file_path.set(filename)

    def load_file(self):
        filepath = self.file_path.get()
        if not filepath:
            messagebox.showerror("Ошибка", "Сначала выберите файл!")
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline()
                if ';' in first_line:
                    sep = ';'
                elif ',' in first_line:
                    sep = ','
                else:
                    sep = None

            self.data = pd.read_csv(filepath, sep=sep, encoding='utf-8', engine='python')

            if len(self.data.columns) < 4:
                raise ValueError("Файл должен содержать минимум 4 столбца")

            numeric_cols = self.data.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) < 3:
                raise ValueError("Недостаточно числовых столбцов")

            first_col = self.data.iloc[:, 0]
            if first_col.dtype == 'object':
                self.point_names = first_col.values
                self.status_var.set(f"Загружены названия для {len(self.point_names)} точек")
            else:
                self.point_names = None
                self.status_var.set("Столбец с названиями не найден или содержит числа")

            if len(self.data.columns) >= 4:
                self.param_columns = list(self.data.columns[3:])
                self.param_combo['values'] = self.param_columns
                if self.param_columns:
                    self.selected_param.set(self.param_columns[0])

            self.status_var.set(f"Загружено {len(self.data)} точек из файла {os.path.basename(filepath)}")
            messagebox.showinfo("Успех", f"Файл загружен успешно!\nНайдено параметров: {len(self.param_columns)}")

            self.update_plot_btn.config(state="normal")
            self.save_plot_btn.config(state="normal")

        except Exception as e:
            messagebox.showerror("Ошибка загрузки", f"Не удалось загрузить файл:\n{str(e)}")
            self.status_var.set("Ошибка загрузки файла")
            print(traceback.format_exc())

    def on_param_selected(self, event):
        if self.selected_param.get():
            self.status_var.set(f"Выбран параметр: {self.selected_param.get()}")

    def toggle_point_names(self):
        if self.last_results is not None:
            self.update_plot()
        else:
            status = "включено" if self.show_point_names.get() else "отключено"
            self.status_var.set(f"Отображение названий точек {status}. Выполните интерполяцию для применения.")

    def toggle_coordinates(self):
        status = "включена" if self.swap_coordinates.get() else "отключена"
        self.status_var.set(f"Замена координат {status}")
        if self.last_results is not None:
            self.update_plot()

    def toggle_contours(self):
        status = "включено" if self.show_contours.get() else "отключено"
        self.status_var.set(f"Отображение изолиний {status}")
        if self.last_results is not None:
            self.update_plot()

    def auto_contour_settings(self):
        if self.last_results is not None:
            zi = self.last_results['zi']
            z_min = np.nanmin(zi)
            z_max = np.nanmax(zi)

            z_min = round(z_min, 1)
            z_max = round(z_max, 1)

            self.contour_min.set(str(z_min))
            self.contour_max.set(str(z_max))

            step = round((z_max - z_min) / 10, 1)
            if step > 0:
                self.contour_step.set(str(step))

            self.status_var.set(f"Автонастройка: мин={z_min}, макс={z_max}, шаг={step}")

    def get_contour_levels(self, zi):
        try:
            if self.contour_min.get() and self.contour_max.get() and self.contour_step.get():
                z_min = float(self.contour_min.get())
                z_max = float(self.contour_max.get())
                step = float(self.contour_step.get())

                if step <= 0:
                    raise ValueError("Шаг должен быть положительным")

                levels = np.arange(z_min, z_max + step, step)

            else:
                n_levels = int(self.contour_levels.get())
                if n_levels < 2:
                    n_levels = 10

                z_min = np.nanmin(zi)
                z_max = np.nanmax(zi)
                levels = np.linspace(z_min, z_max, n_levels)

            return levels

        except ValueError as e:
            self.status_var.set(f"Ошибка в параметрах изолиний: {str(e)}")
            return np.linspace(np.nanmin(zi), np.nanmax(zi), 10)

    def update_plot(self):
        """Обновляет график с безопасной обработкой ошибок"""
        if self.last_results is not None:
            try:
                self.plot_results(
                    self.last_results['xi'],
                    self.last_results['yi'],
                    self.last_results['zi'],
                    self.last_results['x'],
                    self.last_results['y'],
                    self.last_results['z'],
                    self.last_results['names'],
                    self.last_results.get('x_label', "Долгота"),
                    self.last_results.get('y_label', "Широта")
                )
                # Безопасно обновляем тулбар
                self.safe_toolbar_update()
            except ZeroDivisionError as e:
                print(f"Ошибка деления на ноль при обновлении графика: {e}")
                self.status_var.set("Ошибка отображения - попробуйте изменить размер окна")
                # Попытка восстановления
                try:
                    self.figure.set_dpi(100)
                    self.canvas.draw()
                except:
                    pass
            except Exception as e:
                print(f"Ошибка при обновлении графика: {e}")
                self.status_var.set(f"Ошибка обновления: {str(e)[:50]}")

    def create_grid(self, x, y):
        try:
            resolution = int(self.grid_resolution.get())
            if resolution < 10:
                resolution = 10
                self.grid_resolution.set("10")
        except:
            resolution = 50
            self.grid_resolution.set("50")

        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
        x_pad = (x_max - x_min) * 0.05
        y_pad = (y_max - y_min) * 0.05

        xi = np.linspace(x_min - x_pad, x_max + x_pad, resolution)
        yi = np.linspace(y_min - y_pad, y_max + y_pad, resolution)
        xi, yi = np.meshgrid(xi, yi)

        return xi, yi

    def interpolate_b_spline(self, x, y, z, xi, yi):
        try:
            points = np.column_stack((x, y))
            unique_points, indices = np.unique(points, axis=0, return_index=True)

            if len(unique_points) < 4:
                raise ValueError("Недостаточно уникальных точек для B-сплайн интерполяции")

            unique_z = z[indices]

            spline = SmoothBivariateSpline(x[indices], y[indices], unique_z, s=len(unique_points))
            zi = spline.ev(xi, yi)

            return zi
        except Exception as e:
            raise Exception(f"Ошибка B-сплайн интерполяции: {str(e)}")

    def interpolate_tin(self, x, y, z, xi, yi):
        try:
            points = np.column_stack((x, y))

            if len(points) < 3:
                raise ValueError("Недостаточно точек для триангуляции")

            interpolator = LinearNDInterpolator(points, z)
            zi = interpolator(xi, yi)

            mask = np.isnan(zi)
            if mask.any():
                rbf = RBFInterpolator(points, z, kernel='thin_plate_spline')
                zi[mask] = rbf(np.column_stack((xi[mask], yi[mask])))

            return zi
        except Exception as e:
            raise Exception(f"Ошибка TIN интерполяции: {str(e)}")

    def interpolate_idw(self, x, y, z, xi, yi, power=2):
        try:
            points = np.column_stack((x, y))
            xi_flat = xi.flatten()
            yi_flat = yi.flatten()
            zi_flat = np.zeros_like(xi_flat)

            for i, (xii, yii) in enumerate(zip(xi_flat, yi_flat)):
                distances = np.sqrt((xii - x)**2 + (yii - y)**2)

                min_dist_idx = np.argmin(distances)
                if distances[min_dist_idx] < 1e-10:
                    zi_flat[i] = z[min_dist_idx]
                else:
                    weights = 1.0 / (distances ** power)
                    zi_flat[i] = np.sum(weights * z) / np.sum(weights)

            return zi_flat.reshape(xi.shape)
        except Exception as e:
            raise Exception(f"Ошибка IDW интерполяции: {str(e)}")

    def interpolate_barnes(self, x, y, z, xi, yi):
        try:
            lat_to_km = 111.0
            lon_to_km = 111.0 * np.cos(np.mean(y) * np.pi/180)

            x_km = x * lon_to_km
            y_km = y * lat_to_km
            xi_km = xi * lon_to_km
            yi_km = yi * lat_to_km

            n_passes = self.barnes_passes.get()
            gamma = self.barnes_gamma.get()

            points = np.column_stack((x_km, y_km))
            distances = []
            for i in range(len(points)):
                for j in range(i+1, len(points)):
                    dist = np.sqrt(np.sum((points[i] - points[j])**2))
                    if dist > 0:
                        distances.append(dist)

            if distances:
                d_mean = np.mean(distances)
                R = d_mean * 3.0
            else:
                R = 100.0

            xi_flat = xi_km.flatten()
            yi_flat = yi_km.flatten()
            zi_result = np.zeros_like(xi_flat)

            kappa = (R / 2.0)**2

            for pass_num in range(n_passes):
                if pass_num == 0:
                    for i, (xii, yii) in enumerate(zip(xi_flat, yi_flat)):
                        weights = np.exp(-((xii - x_km)**2 + (yii - y_km)**2) / (2 * kappa))
                        weights_sum = np.sum(weights)
                        if weights_sum > 0:
                            zi_result[i] = np.sum(weights * z) / weights_sum
                        else:
                            zi_result[i] = np.mean(z)
                else:
                    kappa = kappa * gamma

                    z_obs_interp = np.zeros_like(z)
                    for j, (xj, yj) in enumerate(zip(x_km, y_km)):
                        weights = np.exp(-((xj - x_km)**2 + (yj - y_km)**2) / (2 * kappa))
                        weights_sum = np.sum(weights)
                        if weights_sum > 0:
                            z_obs_interp[j] = np.sum(weights * z) / weights_sum
                        else:
                            z_obs_interp[j] = np.mean(z)

                    residuals = z - z_obs_interp

                    for i, (xii, yii) in enumerate(zip(xi_flat, yi_flat)):
                        weights = np.exp(-((xii - x_km)**2 + (yii - y_km)**2) / (2 * kappa))
                        weights_sum = np.sum(weights)
                        if weights_sum > 0:
                            correction = np.sum(weights * residuals) / weights_sum
                            zi_result[i] += correction

            return zi_result.reshape(xi.shape)

        except Exception as e:
            raise Exception(f"Ошибка Барнс-интерполяции: {str(e)}")

    def interpolate_cressman(self, x, y, z, xi, yi):
        try:
            lat_to_km = 111.0
            lon_to_km = 111.0 * np.cos(np.mean(y) * np.pi/180)

            x_km = x * lon_to_km
            y_km = y * lat_to_km
            xi_km = xi * lon_to_km
            yi_km = yi * lat_to_km

            n_passes = self.cressman_passes.get()
            R0 = self.cressman_radius.get()
            radius_factor = self.cressman_radius_factor.get()

            xi_flat = xi_km.flatten()
            yi_flat = yi_km.flatten()
            zi_result = np.zeros_like(xi_flat)

            for pass_num in range(n_passes):
                R = R0 * (radius_factor ** pass_num)

                for i, (xii, yii) in enumerate(zip(xi_flat, yi_flat)):
                    distances = np.sqrt((xii - x_km)**2 + (yii - y_km)**2)

                    mask = distances < R

                    if np.any(mask):
                        if pass_num == 0:
                            weights = (R**2 - distances[mask]**2) / (R**2 + distances[mask]**2)
                            zi_result[i] = np.sum(weights * z[mask]) / np.sum(weights)
                        else:
                            z_interp_current = 0
                            weights_sum = 0

                            for j, (xj, yj) in enumerate(zip(x_km, y_km)):
                                dist_j = np.sqrt((xj - x_km)**2 + (yj - y_km)**2)
                                mask_j = dist_j < R
                                if np.any(mask_j):
                                    weights_j = (R**2 - dist_j[mask_j]**2) / (R**2 + dist_j[mask_j]**2)
                                    z_interp_point = np.sum(weights_j * z[mask_j]) / np.sum(weights_j)
                                    residual = z[j] - z_interp_point

                                    weight = (R**2 - distances[j]**2) / (R**2 + distances[j]**2)
                                    if distances[j] < R:
                                        z_interp_current += weight * residual
                                        weights_sum += weight

                            if weights_sum > 0:
                                zi_result[i] += z_interp_current / weights_sum

            return zi_result.reshape(xi.shape)

        except Exception as e:
            raise Exception(f"Ошибка Крессман-интерполяции: {str(e)}")

    def perform_interpolation(self):
        if self.data is None:
            messagebox.showerror("Ошибка", "Сначала загрузите файл с данными!")
            return

        if not self.selected_param.get():
            messagebox.showerror("Ошибка", "Выберите параметр для интерполяции!")
            return

        try:
            self.status_var.set("Выполняется интерполяция...")
            self.root.update()

            if self.swap_coordinates.get():
                x = self.data.iloc[:, 2].values.astype(float)
                y = self.data.iloc[:, 1].values.astype(float)
                x_label = "Широта"
                y_label = "Долгота"
            else:
                x = self.data.iloc[:, 1].values.astype(float)
                y = self.data.iloc[:, 2].values.astype(float)
                x_label = "Долгота"
                y_label = "Широта"

            z = self.data[self.selected_param.get()].values.astype(float)

            try:
                names = self.data.iloc[:, 0].values.astype(str)
            except:
                names = np.array([f"Point_{i}" for i in range(len(x))])

            mask = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
            x = x[mask]
            y = y[mask]
            z = z[mask]
            names = names[mask]

            if len(x) < 4:
                raise ValueError("Недостаточно точек для интерполяции (минимум 4)")

            xi, yi = self.create_grid(x, y)

            method = self.selected_method.get()

            if method == "IDW":
                zi = self.interpolate_idw(x, y, z, xi, yi)
            elif method == "B-сплайн":
                zi = self.interpolate_b_spline(x, y, z, xi, yi)
            elif method == "TIN (Triangulation)":
                zi = self.interpolate_tin(x, y, z, xi, yi)
            elif method == "Барнс (Barnes)":
                zi = self.interpolate_barnes(x, y, z, xi, yi)
            elif method == "Крессман (Cressman)":
                zi = self.interpolate_cressman(x, y, z, xi, yi)
            else:
                zi = self.interpolate_idw(x, y, z, xi, yi)

            self.last_results = {
                'xi': xi,
                'yi': yi,
                'zi': zi,
                'x': x,
                'y': y,
                'z': z,
                'names': names,
                'x_label': x_label,
                'y_label': y_label
            }

            self.auto_contour_settings()
            self.plot_results(xi, yi, zi, x, y, z, names, x_label, y_label)

            coord_status = " (координаты заменены)" if self.swap_coordinates.get() else ""
            self.status_var.set(f"Интерполяция методом '{method}' выполнена успешно{coord_status}")

        except Exception as e:
            messagebox.showerror("Ошибка интерполяции", str(e))
            self.status_var.set("Ошибка при выполнении интерполяции")
            print(traceback.format_exc())

    def plot_results(self, xi, yi, zi, x, y, z, names=None, x_label="Долгота", y_label="Широта"):
        """Отображает результаты интерполяции с улучшенной картой"""

        # Обработка возможных проблем с DPI
        try:
            self.figure.clear()
            # Безопасное установление DPI
            current_dpi = getattr(self.figure, 'dpi', 100)
            if current_dpi <= 0:
                self.figure.set_dpi(100)
            else:
                self.figure.set_dpi(min(max(current_dpi, 100), 150))
        except Exception as e:
            print(f"Ошибка при очистке фигуры: {e}")
            # Создаем новую фигуру при ошибке
            self.figure = plt.Figure(figsize=(12, 9), dpi=100)
            # Находим фрейм для графика
            for child in self.right_panel.winfo_children():
                if isinstance(child, ttk.LabelFrame) and "Результат интерполяции" in child.cget("text"):
                    self.canvas = FigureCanvasTkAgg(self.figure, master=child)
                    self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
                    break

        if self.show_map.get() and CARTOPY_AVAILABLE:
            # Используем проекцию PlateCarree для базовой карты
            ax = self.figure.add_subplot(111, projection=ccrs.PlateCarree())

            # Настройка качества отображения
            ax.set_facecolor('#e6f3ff')  # Цвет океана

            # Добавляем базовые слои в зависимости от выбранного типа карты
            if self.map_type.get() == "detailed":
                # Детальная карта с полным набором слоев
                # Суша и океан с улучшенной графикой
                ax.add_feature(cfeature.LAND, facecolor='#f0e8d0', edgecolor='none', alpha=0.7)
                ax.add_feature(cfeature.OCEAN, facecolor='#c8e4f0', alpha=0.7)

                # Добавляем береговые линии с повышенной четкостью
                ax.add_feature(cfeature.COASTLINE.with_scale(self.map_resolution.get()),
                              linewidth=0.8, alpha=0.9, edgecolor='#2c3e50')

                # Границы государств
                if self.show_country_borders.get():
                    ax.add_feature(cfeature.BORDERS.with_scale(self.map_resolution.get()),
                                  linewidth=0.8, alpha=0.8, edgecolor='#34495e', linestyle='-')

                # Административные границы
                if self.show_admin_borders.get():
                    try:
                        # Используем административные границы первого уровня
                        ax.add_feature(cfeature.ADMIN_1.with_scale(self.map_resolution.get()),
                                      linewidth=0.5, alpha=0.6, edgecolor='#7f8c8d', linestyle=':')
                    except:
                        # Если нет данных, пропускаем
                        pass

                # Реки
                if self.show_rivers.get():
                    ax.add_feature(cfeature.RIVERS.with_scale(self.map_resolution.get()),
                                  linewidth=0.6, alpha=0.7, edgecolor='#3498db')

                # Озера
                if self.show_lakes.get():
                    ax.add_feature(cfeature.LAKES.with_scale(self.map_resolution.get()),
                                  facecolor='#87ceeb', alpha=0.6)

                # Дороги (требует загрузки дополнительных данных)
                if self.show_roads.get():
                    try:
                        ax.add_feature(cfeature.ROADS.with_scale(self.map_resolution.get()),
                                      linewidth=0.4, alpha=0.5, edgecolor='#95a5a6')
                    except:
                        pass

            elif self.map_type.get() == "physical":
                # Физическая карта с рельефом
                ax.add_feature(cfeature.LAND, facecolor='#d4c5a9', alpha=0.7)
                ax.add_feature(cfeature.OCEAN, facecolor='#a4cde0', alpha=0.7)
                ax.add_feature(cfeature.COASTLINE.with_scale(self.map_resolution.get()), linewidth=0.8)
                if self.show_country_borders.get():
                    ax.add_feature(cfeature.BORDERS.with_scale(self.map_resolution.get()),
                                  linewidth=0.6, alpha=0.7, linestyle='-')

            elif self.map_type.get() == "political":
                # Политическая карта с акцентом на границы
                ax.add_feature(cfeature.LAND, facecolor='#e8e0c8', alpha=0.5)
                ax.add_feature(cfeature.OCEAN, facecolor='#c8e4f0', alpha=0.5)
                ax.add_feature(cfeature.COASTLINE.with_scale(self.map_resolution.get()), linewidth=1.0)
                ax.add_feature(cfeature.BORDERS.with_scale(self.map_resolution.get()),
                              linewidth=1.2, alpha=0.9, edgecolor='#2c3e50')
                ax.add_feature(cfeature.STATES.with_scale(self.map_resolution.get()),
                              linewidth=0.5, alpha=0.6, edgecolor='#7f8c8d')

            elif self.map_type.get() == "relief":
                # Карта рельефа
                try:
                    ax.add_feature(cfeature.OCEAN, facecolor='#7cb5ec', alpha=0.6)
                    ax.add_feature(cfeature.LAND, facecolor='#c8b89a', alpha=0.5)
                    # Добавляем рельеф (требует установки дополнительных данных)
                    ax.add_feature(cfeature.MOUNTAINS.with_scale(self.map_resolution.get()),
                                  facecolor='#8b7355', alpha=0.4)
                except:
                    ax.add_feature(cfeature.LAND, facecolor='#d4c5a9')
                ax.add_feature(cfeature.COASTLINE.with_scale(self.map_resolution.get()), linewidth=0.8)
                if self.show_country_borders.get():
                    ax.add_feature(cfeature.BORDERS.with_scale(self.map_resolution.get()), linewidth=0.5)

            elif self.map_type.get() == "satellite":
                # Имитация спутникового снимка
                ax.add_feature(cfeature.LAND, facecolor='#7cb518', alpha=0.6)
                ax.add_feature(cfeature.OCEAN, facecolor='#2c7da0', alpha=0.6)
                ax.add_feature(cfeature.COASTLINE.with_scale(self.map_resolution.get()), linewidth=1.0)
                if self.show_country_borders.get():
                    ax.add_feature(cfeature.BORDERS.with_scale(self.map_resolution.get()),
                                  linewidth=0.8, edgecolor='white', alpha=0.8)

            # Добавляем сетку координат с улучшенным оформлением
            gl = ax.gridlines(draw_labels=True, alpha=0.4, linestyle='--', linewidth=0.5, color='gray')
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {'size': 9, 'color': '#2c3e50', 'weight': 'bold'}
            gl.ylabel_style = {'size': 9, 'color': '#2c3e50', 'weight': 'bold'}

            # Устанавливаем границы карты по данным, если они заданы
            if self.map_extent is not None:
                ax.set_extent(self.map_extent, crs=ccrs.PlateCarree())
            else:
                # Автоматическая установка границ с отступом
                x_min, x_max = xi.min(), xi.max()
                y_min, y_max = yi.min(), yi.max()
                x_pad = (x_max - x_min) * 0.1
                y_pad = (y_max - y_min) * 0.1
                ax.set_extent([x_min - x_pad, x_max + x_pad, y_min - y_pad, y_max + y_pad],
                            crs=ccrs.PlateCarree())

        elif self.show_map.get() and not CARTOPY_AVAILABLE:
            # Упрощенная карта если Cartopy не установлен
            ax = self.figure.add_subplot(111)
            ax.set_facecolor('#e6f3ff')
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.text(0.5, 0.95, 'Для качественных карт установите Cartopy\npip install cartopy',
                   transform=ax.transAxes, ha='center', fontsize=10,
                   bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
        else:
            # Обычный график без карты
            ax = self.figure.add_subplot(111)

        # Выбираем палитру
        palette = self.color_palette.get()
        if self.reverse_palette.get():
            palette = palette + '_r'

        n_colors = self.n_colors.get()

        # Контурный график интерполяции
        contourf = ax.contourf(xi, yi, zi, levels=n_colors, cmap=palette,
                               alpha=self.interp_alpha.get(), zorder=2)

        # Добавляем цветовую шкалу
        cbar = self.figure.colorbar(contourf, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(self.selected_param.get(), fontsize=10, fontweight='bold')

        # Изолинии
        if self.show_contours.get():
            levels = self.get_contour_levels(zi)
            contours = ax.contour(xi, yi, zi, levels=levels, colors='black',
                                 linewidths=0.8, alpha=0.7, zorder=3)
            ax.clabel(contours, inline=True, fontsize=8, fmt='%.1f', inline_spacing=5)

        # Отображение точек
        scatter = ax.scatter(x, y, c=z, s=40, edgecolors='white', linewidth=1,
                           cmap=palette, vmin=zi.min(), vmax=zi.max(),
                           zorder=2, alpha=1.0)

        # Названия точек - УМЕНЬШЕННЫЕ И ПРОЗРАЧНЫЕ как в предыдущей версии
        if self.show_point_names.get() and names is not None:
            for i, (xi_point, yi_point, name) in enumerate(zip(x, y, names)):
                clean_name = str(name).strip()
                if clean_name and clean_name.lower() != 'nan':
                    ax.annotate(clean_name, (xi_point, yi_point),
                              xytext=(3, 3), textcoords='offset points',  # Уменьшен отступ
                              fontsize=7,  # Уменьшен размер шрифта с 8 до 7
                              fontweight='normal',  # Обычный шрифт вместо жирного
                              alpha=0.7,  # Добавлена прозрачность
                              bbox=dict(boxstyle='round,pad=0.2',  # Уменьшен padding
                                      facecolor='yellow',
                                      alpha=0.5,  # Уменьшена прозрачность фона
                                      edgecolor='none'),  # Убран контур
                              zorder=5)

        # Подписи осей
        ax.set_xlabel(x_label, fontsize=10, fontweight='bold')
        ax.set_ylabel(y_label, fontsize=10, fontweight='bold')

        # Заголовок с информацией
        title_parts = [f'{self.selected_method.get()}: {self.selected_param.get()}']
        if self.show_map.get() and CARTOPY_AVAILABLE:
            title_parts.append(f'карта ({self.map_type.get()})')

        title = ' | '.join(title_parts)
        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)

        # Компактное размещение
        self.figure.tight_layout()
        self.canvas.draw()

    def save_plot(self):
        if self.last_results is None:
            messagebox.showerror("Ошибка", "Нет графика для сохранения!")
            return

        filename = filedialog.asksaveasfilename(
            title="Сохранить график",
            defaultextension=".png",
            filetypes=[
                ("PNG файлы", "*.png"),
                ("JPEG файлы", "*.jpg"),
                ("PDF файлы", "*.pdf"),
                ("SVG файлы", "*.svg"),
                ("Все файлы", "*.*")
            ]
        )

        if filename:
            try:
                # Сохраняем с высоким DPI для качества
                self.figure.savefig(filename, dpi=300, bbox_inches='tight')
                self.status_var.set(f"График сохранен: {os.path.basename(filename)}")
                messagebox.showinfo("Успех", f"График успешно сохранен:\n{filename}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить график:\n{str(e)}")

    def exit_program(self):
        """Завершение работы программы"""
        if messagebox.askyesno("Подтверждение", "Вы действительно хотите выйти?"):
            self.root.quit()
            self.root.destroy()


def main():
    root = tk.Tk()
    app = GeoInterpolationApp(root)

    if len(sys.argv) > 1:
        filename = sys.argv[1]
        if os.path.exists(filename):
            app.file_path.set(os.path.abspath(filename))
            app.status_var.set(f"Найден файл: {filename}. Нажмите 'Загрузить'.")

    root.mainloop()


if __name__ == "__main__":
    main()
