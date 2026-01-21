#!/usr/bin/env python3
"""
Image Upscaler & Processor
A GUI application to upscale images, remove backgrounds (AI or threshold-based),
resize by inches, and export to JPEG and TIFF formats.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import os
from pathlib import Path
import threading
from collections import deque

# Try to import backgroundremover for AI-based removal
try:
    from backgroundremover import bg
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


class ImageProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Upscaler & Processor")
        self.root.geometry("1100x800")
        self.root.minsize(900, 700)

        # Image state
        self.original_image = None
        self.processed_image = None
        self.preview_image = None
        self.current_file_path = None
        self.bg_removed_cache = None  # Cache for AI background removal

        # Manual editing state
        self.edit_history = []  # Stack of previous states for undo
        self.max_history = 20  # Maximum undo steps
        self.magic_wand_mode = tk.BooleanVar(value=False)
        self.magic_wand_tolerance = tk.IntVar(value=32)

        # Preview scaling info (for click coordinate mapping)
        self.preview_scale = 1.0
        self.preview_offset_x = 0
        self.preview_offset_y = 0

        # Processing parameters
        self.scale_factor = tk.DoubleVar(value=1.0)
        self.white_threshold = tk.IntVar(value=240)
        self.remove_background = tk.BooleanVar(value=False)
        self.bg_removal_method = tk.StringVar(value="ai" if AI_AVAILABLE else "threshold")
        self.width_inches = tk.DoubleVar(value=0.0)
        self.height_inches = tk.DoubleVar(value=0.0)
        self.dpi = tk.IntVar(value=300)
        self.lock_aspect_ratio = tk.BooleanVar(value=True)

        # Track if user is manually editing dimensions
        self.updating_dimensions = False
        self.processing = False

        self.setup_ui()

    def setup_ui(self):
        """Set up the main UI layout."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # Left panel - Controls
        self.setup_controls_panel(main_frame)

        # Right panel - Preview
        self.setup_preview_panel(main_frame)

        # Bottom panel - Export buttons
        self.setup_export_panel(main_frame)

    def setup_controls_panel(self, parent):
        """Set up the controls panel on the left side."""
        # Create a container frame for the controls and scrollbar
        controls_container = ttk.Frame(parent, width=320)
        controls_container.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 10))
        controls_container.grid_propagate(False)  # Prevent container from shrinking
        controls_container.rowconfigure(0, weight=1)
        controls_container.columnconfigure(0, weight=1)

        # Create a canvas with scrollbar for the controls
        controls_canvas = tk.Canvas(controls_container, width=300, highlightthickness=0)
        controls_scrollbar = ttk.Scrollbar(controls_container, orient="vertical", command=controls_canvas.yview)
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)

        controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar.grid(row=0, column=1, sticky="ns")

        # Create frame inside canvas
        controls_frame = ttk.LabelFrame(controls_canvas, text="Controls", padding="10")
        canvas_window = controls_canvas.create_window((0, 0), window=controls_frame, anchor="nw")

        # Update canvas width when the controls frame changes size
        def on_frame_configure(event):
            controls_canvas.configure(scrollregion=controls_canvas.bbox("all"))
            # Make canvas window width match canvas width
            controls_canvas.itemconfig(canvas_window, width=controls_canvas.winfo_width())

        controls_frame.bind("<Configure>", on_frame_configure)

        # File selection
        ttk.Label(controls_frame, text="Image File:").grid(row=0, column=0, sticky="w", pady=(0, 5))

        file_frame = ttk.Frame(controls_frame)
        file_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))

        self.file_label = ttk.Label(file_frame, text="No file selected", width=25, anchor="w")
        self.file_label.grid(row=0, column=0, sticky="w")

        ttk.Button(file_frame, text="Browse...", command=self.browse_file).grid(row=0, column=1, padx=(10, 0))

        ttk.Separator(controls_frame, orient="horizontal").grid(row=2, column=0, sticky="ew", pady=10)

        # Upscaling section
        ttk.Label(controls_frame, text="Upscale Factor:", font=("", 10, "bold")).grid(row=3, column=0, sticky="w", pady=(0, 5))

        scale_frame = ttk.Frame(controls_frame)
        scale_frame.grid(row=4, column=0, sticky="ew", pady=(0, 15))

        self.scale_slider = ttk.Scale(scale_frame, from_=1.0, to=8.0, variable=self.scale_factor,
                                       orient="horizontal", length=150, command=self.on_scale_change)
        self.scale_slider.grid(row=0, column=0, sticky="w")

        self.scale_label = ttk.Label(scale_frame, text="1.0x")
        self.scale_label.grid(row=0, column=1, padx=(10, 0))

        ttk.Label(controls_frame, text="Custom scale:").grid(row=5, column=0, sticky="w")
        self.scale_entry = ttk.Entry(controls_frame, width=10)
        self.scale_entry.grid(row=6, column=0, sticky="w", pady=(0, 15))
        self.scale_entry.insert(0, "1.0")
        self.scale_entry.bind("<Return>", self.on_scale_entry)
        self.scale_entry.bind("<FocusOut>", self.on_scale_entry)

        ttk.Separator(controls_frame, orient="horizontal").grid(row=7, column=0, sticky="ew", pady=10)

        # Background removal section
        ttk.Label(controls_frame, text="Background Removal:", font=("", 10, "bold")).grid(row=8, column=0, sticky="w", pady=(0, 5))

        ttk.Checkbutton(controls_frame, text="Remove background",
                        variable=self.remove_background, command=self.on_bg_toggle).grid(row=9, column=0, sticky="w")

        # Method selection
        method_frame = ttk.Frame(controls_frame)
        method_frame.grid(row=10, column=0, sticky="w", pady=(5, 0))

        ai_text = "AI-based (recommended)" if AI_AVAILABLE else "AI-based (not installed)"
        self.ai_radio = ttk.Radiobutton(method_frame, text=ai_text, variable=self.bg_removal_method,
                                         value="ai", command=self.on_method_change)
        self.ai_radio.grid(row=0, column=0, sticky="w")
        if not AI_AVAILABLE:
            self.ai_radio.configure(state="disabled")

        ttk.Radiobutton(method_frame, text="White threshold", variable=self.bg_removal_method,
                        value="threshold", command=self.on_method_change).grid(row=1, column=0, sticky="w")

        # Threshold controls (only shown for threshold method)
        self.threshold_frame = ttk.Frame(controls_frame)
        self.threshold_frame.grid(row=11, column=0, sticky="ew", pady=(10, 15))

        ttk.Label(self.threshold_frame, text="White threshold (0-255):").grid(row=0, column=0, sticky="w")

        threshold_slider_frame = ttk.Frame(self.threshold_frame)
        threshold_slider_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.threshold_slider = ttk.Scale(threshold_slider_frame, from_=200, to=255, variable=self.white_threshold,
                                          orient="horizontal", length=150, command=self.on_threshold_change)
        self.threshold_slider.grid(row=0, column=0, sticky="w")

        self.threshold_label = ttk.Label(threshold_slider_frame, text="240")
        self.threshold_label.grid(row=0, column=1, padx=(10, 0))

        # Initially hide threshold controls if AI is selected
        self.update_threshold_visibility()

        ttk.Separator(controls_frame, orient="horizontal").grid(row=12, column=0, sticky="ew", pady=10)

        # === Magic Wand / Manual Cleanup Section ===
        ttk.Label(controls_frame, text="Manual Cleanup:", font=("", 10, "bold")).grid(row=13, column=0, sticky="w", pady=(0, 5))

        # Magic wand toggle
        self.magic_wand_check = ttk.Checkbutton(controls_frame, text="Magic Wand (click to remove)",
                                                 variable=self.magic_wand_mode, command=self.on_magic_wand_toggle)
        self.magic_wand_check.grid(row=14, column=0, sticky="w")

        # Tolerance slider
        tolerance_frame = ttk.Frame(controls_frame)
        tolerance_frame.grid(row=15, column=0, sticky="ew", pady=(5, 0))

        ttk.Label(tolerance_frame, text="Tolerance (0-255):").grid(row=0, column=0, sticky="w")

        tolerance_slider_frame = ttk.Frame(tolerance_frame)
        tolerance_slider_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.tolerance_slider = ttk.Scale(tolerance_slider_frame, from_=0, to=128, variable=self.magic_wand_tolerance,
                                          orient="horizontal", length=150, command=self.on_tolerance_change)
        self.tolerance_slider.grid(row=0, column=0, sticky="w")

        self.tolerance_label = ttk.Label(tolerance_slider_frame, text="32")
        self.tolerance_label.grid(row=0, column=1, padx=(10, 0))

        # Undo button
        undo_frame = ttk.Frame(controls_frame)
        undo_frame.grid(row=16, column=0, sticky="w", pady=(10, 0))

        self.undo_button = ttk.Button(undo_frame, text="Undo", command=self.undo_edit, state="disabled")
        self.undo_button.grid(row=0, column=0, padx=(0, 10))

        self.undo_label = ttk.Label(undo_frame, text="(0 steps)")
        self.undo_label.grid(row=0, column=1)

        # Instructions
        self.magic_wand_instructions = ttk.Label(controls_frame,
                                                  text="Click on areas in preview\nto make them transparent",
                                                  foreground="gray", font=("", 9))
        self.magic_wand_instructions.grid(row=17, column=0, sticky="w", pady=(5, 0))
        self.magic_wand_instructions.grid_remove()  # Hidden by default

        ttk.Separator(controls_frame, orient="horizontal").grid(row=18, column=0, sticky="ew", pady=10)

        # Size section
        ttk.Label(controls_frame, text="Output Size (inches):", font=("", 10, "bold")).grid(row=19, column=0, sticky="w", pady=(0, 5))

        ttk.Label(controls_frame, text="DPI:").grid(row=20, column=0, sticky="w")
        dpi_frame = ttk.Frame(controls_frame)
        dpi_frame.grid(row=21, column=0, sticky="w", pady=(0, 10))

        dpi_combo = ttk.Combobox(dpi_frame, textvariable=self.dpi, values=[72, 150, 300, 600], width=8)
        dpi_combo.grid(row=0, column=0)
        dpi_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        ttk.Checkbutton(controls_frame, text="Lock aspect ratio",
                        variable=self.lock_aspect_ratio).grid(row=22, column=0, sticky="w")

        size_frame = ttk.Frame(controls_frame)
        size_frame.grid(row=23, column=0, sticky="w", pady=(10, 0))

        ttk.Label(size_frame, text="Width:").grid(row=0, column=0, sticky="w")
        self.width_entry = ttk.Entry(size_frame, width=10)
        self.width_entry.grid(row=0, column=1, padx=(5, 10))
        self.width_entry.bind("<Return>", self.on_width_change)
        self.width_entry.bind("<FocusOut>", self.on_width_change)

        ttk.Label(size_frame, text="Height:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.height_entry = ttk.Entry(size_frame, width=10)
        self.height_entry.grid(row=1, column=1, padx=(5, 10), pady=(5, 0))
        self.height_entry.bind("<Return>", self.on_height_change)
        self.height_entry.bind("<FocusOut>", self.on_height_change)

        # Image info
        ttk.Separator(controls_frame, orient="horizontal").grid(row=24, column=0, sticky="ew", pady=10)
        ttk.Label(controls_frame, text="Image Info:", font=("", 10, "bold")).grid(row=25, column=0, sticky="w", pady=(0, 5))

        self.info_label = ttk.Label(controls_frame, text="No image loaded", justify="left")
        self.info_label.grid(row=26, column=0, sticky="w")

        # Status label for processing
        self.status_label = ttk.Label(controls_frame, text="", foreground="blue")
        self.status_label.grid(row=27, column=0, sticky="w", pady=(10, 0))

        # Bind mousewheel for scrolling (only when mouse is over controls)
        def on_mousewheel(event):
            controls_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        def bind_mousewheel(event):
            controls_canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_mousewheel(event):
            controls_canvas.unbind_all("<MouseWheel>")

        controls_canvas.bind("<Enter>", bind_mousewheel)
        controls_canvas.bind("<Leave>", unbind_mousewheel)

    def setup_preview_panel(self, parent):
        """Set up the preview panel on the right side."""
        preview_frame = ttk.LabelFrame(parent, text="Preview", padding="10")
        preview_frame.grid(row=0, column=1, rowspan=2, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        # Canvas for image preview
        self.canvas = tk.Canvas(preview_frame, bg="#f0f0f0", cursor="arrow")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbars
        v_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.canvas.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.canvas.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        # Bind click event for magic wand
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        # Preview update button
        ttk.Button(preview_frame, text="Update Preview", command=self.update_preview).grid(row=2, column=0, pady=(10, 0))

    def setup_export_panel(self, parent):
        """Set up the export panel at the bottom."""
        export_frame = ttk.Frame(parent, padding="10")
        export_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        ttk.Button(export_frame, text="Export as JPEG", command=self.export_jpeg).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(export_frame, text="Export as TIFF", command=self.export_tiff).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(export_frame, text="Export Both", command=self.export_both).grid(row=0, column=2)

    def on_magic_wand_toggle(self):
        """Handle magic wand mode toggle."""
        if self.magic_wand_mode.get():
            self.canvas.configure(cursor="crosshair")
            self.magic_wand_instructions.grid()
            self.status_label.config(text="Magic Wand: Click on areas to remove")
        else:
            self.canvas.configure(cursor="arrow")
            self.magic_wand_instructions.grid_remove()
            self.status_label.config(text="")

    def on_tolerance_change(self, value):
        """Handle tolerance slider change."""
        tolerance = int(float(value))
        self.tolerance_label.config(text=str(tolerance))

    def on_canvas_click(self, event):
        """Handle click on canvas for magic wand tool."""
        if not self.magic_wand_mode.get() or self.processed_image is None:
            return

        # Get click coordinates relative to canvas
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Convert to image coordinates
        img_x, img_y = self.canvas_to_image_coords(canvas_x, canvas_y)

        if img_x is None or img_y is None:
            return

        # Perform flood fill to make area transparent
        self.flood_fill_transparent(img_x, img_y)

    def canvas_to_image_coords(self, canvas_x, canvas_y):
        """Convert canvas coordinates to image coordinates."""
        if self.processed_image is None:
            return None, None

        # Get canvas dimensions
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        # Image is centered in canvas
        img_width, img_height = self.processed_image.size

        # Calculate displayed size (same logic as update_preview)
        scale = min(canvas_width / img_width, canvas_height / img_height, 1.0)
        display_width = int(img_width * scale)
        display_height = int(img_height * scale)

        # Calculate offset (image is centered)
        offset_x = (canvas_width - display_width) // 2
        offset_y = (canvas_height - display_height) // 2

        # Convert click to image coordinates
        img_x = int((canvas_x - offset_x) / scale)
        img_y = int((canvas_y - offset_y) / scale)

        # Check bounds
        if img_x < 0 or img_x >= img_width or img_y < 0 or img_y >= img_height:
            return None, None

        return img_x, img_y

    def save_edit_state(self):
        """Save current state for undo."""
        if self.processed_image is not None:
            # Limit history size
            if len(self.edit_history) >= self.max_history:
                self.edit_history.pop(0)

            self.edit_history.append(self.processed_image.copy())
            self.update_undo_button()

    def update_undo_button(self):
        """Update undo button state and label."""
        steps = len(self.edit_history)
        if steps > 0:
            self.undo_button.configure(state="normal")
        else:
            self.undo_button.configure(state="disabled")
        self.undo_label.config(text=f"({steps} steps)")

    def undo_edit(self):
        """Undo the last edit."""
        if len(self.edit_history) > 0:
            self.processed_image = self.edit_history.pop()
            self.update_undo_button()
            self.refresh_preview_display()
            self.status_label.config(text="Undo successful")

    def flood_fill_transparent(self, start_x, start_y):
        """Flood fill from the given point, making matching pixels transparent."""
        if self.processed_image is None:
            return

        # Save state for undo
        self.save_edit_state()

        # Ensure image is RGBA
        if self.processed_image.mode != "RGBA":
            self.processed_image = self.processed_image.convert("RGBA")

        img_width, img_height = self.processed_image.size
        pixels = self.processed_image.load()

        # Get the color at the starting point
        target_color = pixels[start_x, start_y]

        # If already transparent, do nothing
        if len(target_color) == 4 and target_color[3] == 0:
            self.edit_history.pop()  # Remove the saved state since we didn't change anything
            self.update_undo_button()
            self.status_label.config(text="Area is already transparent")
            return

        tolerance = self.magic_wand_tolerance.get()

        # BFS flood fill
        visited = set()
        queue = deque([(start_x, start_y)])
        pixels_changed = 0

        def color_matches(c1, c2):
            """Check if two colors match within tolerance."""
            # Compare RGB values (ignore alpha for matching)
            r1, g1, b1 = c1[0], c1[1], c1[2]
            r2, g2, b2 = c2[0], c2[1], c2[2]
            return (abs(r1 - r2) <= tolerance and
                    abs(g1 - g2) <= tolerance and
                    abs(b1 - b2) <= tolerance)

        while queue:
            x, y = queue.popleft()

            if (x, y) in visited:
                continue

            if x < 0 or x >= img_width or y < 0 or y >= img_height:
                continue

            current_color = pixels[x, y]

            # Skip if already transparent
            if len(current_color) == 4 and current_color[3] == 0:
                visited.add((x, y))
                continue

            if not color_matches(current_color, target_color):
                visited.add((x, y))
                continue

            # Make pixel transparent
            pixels[x, y] = (current_color[0], current_color[1], current_color[2], 0)
            pixels_changed += 1
            visited.add((x, y))

            # Add neighbors (4-connected)
            queue.append((x + 1, y))
            queue.append((x - 1, y))
            queue.append((x, y + 1))
            queue.append((x, y - 1))

        # Update the display
        self.refresh_preview_display()
        self.status_label.config(text=f"Removed {pixels_changed} pixels")

    def refresh_preview_display(self):
        """Refresh the preview display without reprocessing the image."""
        if self.processed_image is None:
            return

        # Get canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width < 10:
            canvas_width = 500
            canvas_height = 400

        # Calculate preview size
        img_width, img_height = self.processed_image.size
        scale = min(canvas_width / img_width, canvas_height / img_height, 1.0)
        preview_width = int(img_width * scale)
        preview_height = int(img_height * scale)

        # Create preview image
        preview = self.processed_image.copy()
        preview.thumbnail((preview_width, preview_height), Image.LANCZOS)

        # Create checkerboard background for transparent images
        if self.processed_image.mode == "RGBA":
            checker = self.create_checkerboard(preview.size)
            checker.paste(preview, mask=preview.split()[3])
            preview = checker

        # Convert to PhotoImage
        self.preview_image = ImageTk.PhotoImage(preview)

        # Update canvas
        self.canvas.delete("all")
        self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.preview_image)
        self.canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))

        # Update info label
        proc_width, proc_height = self.processed_image.size
        if self.original_image:
            orig_width, orig_height = self.original_image.size
        else:
            orig_width, orig_height = proc_width, proc_height
        mode = self.processed_image.mode
        self.info_label.config(
            text=f"Original: {orig_width}x{orig_height}px\n"
                 f"Processed: {proc_width}x{proc_height}px\n"
                 f"Mode: {mode}"
        )

    def update_threshold_visibility(self):
        """Show/hide threshold controls based on selected method."""
        if self.bg_removal_method.get() == "threshold":
            self.threshold_frame.grid()
        else:
            self.threshold_frame.grid_remove()

    def on_method_change(self):
        """Handle background removal method change."""
        self.update_threshold_visibility()
        self.bg_removed_cache = None  # Clear cache when method changes

    def on_bg_toggle(self):
        """Handle background removal toggle."""
        self.update_preview()

    def browse_file(self):
        """Open file dialog to select an image."""
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[
                ("JPEG files", "*.jpg *.jpeg"),
                ("All image files", "*.jpg *.jpeg *.png *.bmp *.gif"),
                ("All files", "*.*")
            ]
        )

        if file_path:
            self.load_image(file_path)

    def load_image(self, file_path):
        """Load an image from the given path."""
        try:
            self.original_image = Image.open(file_path)
            self.current_file_path = file_path
            self.bg_removed_cache = None  # Clear cache for new image
            self.edit_history = []  # Clear edit history
            self.update_undo_button()

            # Update file label
            filename = os.path.basename(file_path)
            if len(filename) > 25:
                filename = filename[:22] + "..."
            self.file_label.config(text=filename)

            # Update dimensions in inches based on current DPI
            width_px, height_px = self.original_image.size
            dpi = self.dpi.get()

            self.width_inches.set(round(width_px / dpi, 2))
            self.height_inches.set(round(height_px / dpi, 2))

            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, str(self.width_inches.get()))
            self.height_entry.delete(0, tk.END)
            self.height_entry.insert(0, str(self.height_inches.get()))

            # Update info label
            mode = self.original_image.mode
            self.info_label.config(text=f"Original: {width_px}x{height_px}px\nMode: {mode}")

            # Reset scale factor
            self.scale_factor.set(1.0)
            self.scale_label.config(text="1.0x")
            self.scale_entry.delete(0, tk.END)
            self.scale_entry.insert(0, "1.0")

            # Update preview
            self.update_preview()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image:\n{str(e)}")

    def on_scale_change(self, value):
        """Handle scale slider change."""
        scale = round(float(value), 1)
        self.scale_label.config(text=f"{scale}x")
        self.scale_entry.delete(0, tk.END)
        self.scale_entry.insert(0, str(scale))
        self.update_dimensions_from_scale()

    def on_scale_entry(self, event=None):
        """Handle custom scale entry."""
        try:
            scale = float(self.scale_entry.get())
            if scale < 0.1:
                scale = 0.1
            elif scale > 20:
                scale = 20
            self.scale_factor.set(scale)
            self.scale_label.config(text=f"{scale}x")
            self.update_dimensions_from_scale()
        except ValueError:
            pass

    def update_dimensions_from_scale(self):
        """Update inch dimensions based on current scale factor."""
        if self.original_image and not self.updating_dimensions:
            self.updating_dimensions = True
            width_px, height_px = self.original_image.size
            scale = self.scale_factor.get()
            dpi = self.dpi.get()

            new_width_inches = round((width_px * scale) / dpi, 2)
            new_height_inches = round((height_px * scale) / dpi, 2)

            self.width_inches.set(new_width_inches)
            self.height_inches.set(new_height_inches)

            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, str(new_width_inches))
            self.height_entry.delete(0, tk.END)
            self.height_entry.insert(0, str(new_height_inches))
            self.updating_dimensions = False

    def on_threshold_change(self, value):
        """Handle threshold slider change."""
        threshold = int(float(value))
        self.threshold_label.config(text=str(threshold))

    def on_width_change(self, event=None):
        """Handle width entry change."""
        if self.updating_dimensions or not self.original_image:
            return

        try:
            new_width = float(self.width_entry.get())
            if new_width <= 0:
                return

            self.updating_dimensions = True
            self.width_inches.set(new_width)

            if self.lock_aspect_ratio.get():
                # Calculate new height maintaining aspect ratio
                orig_width, orig_height = self.original_image.size
                aspect_ratio = orig_height / orig_width
                new_height = round(new_width * aspect_ratio, 2)
                self.height_inches.set(new_height)
                self.height_entry.delete(0, tk.END)
                self.height_entry.insert(0, str(new_height))

            # Update scale factor based on new width
            dpi = self.dpi.get()
            orig_width = self.original_image.size[0]
            new_scale = (new_width * dpi) / orig_width
            self.scale_factor.set(round(new_scale, 2))
            self.scale_label.config(text=f"{round(new_scale, 2)}x")
            self.scale_entry.delete(0, tk.END)
            self.scale_entry.insert(0, str(round(new_scale, 2)))

            self.updating_dimensions = False
        except ValueError:
            self.updating_dimensions = False

    def on_height_change(self, event=None):
        """Handle height entry change."""
        if self.updating_dimensions or not self.original_image:
            return

        try:
            new_height = float(self.height_entry.get())
            if new_height <= 0:
                return

            self.updating_dimensions = True
            self.height_inches.set(new_height)

            if self.lock_aspect_ratio.get():
                # Calculate new width maintaining aspect ratio
                orig_width, orig_height = self.original_image.size
                aspect_ratio = orig_width / orig_height
                new_width = round(new_height * aspect_ratio, 2)
                self.width_inches.set(new_width)
                self.width_entry.delete(0, tk.END)
                self.width_entry.insert(0, str(new_width))

            # Update scale factor based on new height
            dpi = self.dpi.get()
            orig_height = self.original_image.size[1]
            new_scale = (new_height * dpi) / orig_height
            self.scale_factor.set(round(new_scale, 2))
            self.scale_label.config(text=f"{round(new_scale, 2)}x")
            self.scale_entry.delete(0, tk.END)
            self.scale_entry.insert(0, str(round(new_scale, 2)))

            self.updating_dimensions = False
        except ValueError:
            self.updating_dimensions = False

    def remove_background_ai(self, img):
        """Remove background using AI (backgroundremover)."""
        if not AI_AVAILABLE:
            return img

        # Use cached result if available
        if self.bg_removed_cache is not None:
            return self.bg_removed_cache.copy()

        self.status_label.config(text="Processing with AI... (first time may take a moment)")
        self.root.update()

        try:
            # Convert PIL image to bytes
            import io
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            # Process with backgroundremover
            output = bg.remove(img_byte_arr.read())

            # Convert back to PIL image
            result = Image.open(io.BytesIO(output))

            # Cache the result
            self.bg_removed_cache = result.copy()

            self.status_label.config(text="")
            return result

        except Exception as e:
            self.status_label.config(text=f"AI error: {str(e)[:30]}...")
            messagebox.showerror("AI Background Removal Error",
                               f"Failed to remove background with AI:\n{str(e)}\n\nFalling back to threshold method.")
            return self.remove_white_background(img)

    def remove_white_background(self, img):
        """Remove white/near-white background from image using threshold."""
        # Convert to RGBA if necessary
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Get pixel data
        data = img.getdata()
        threshold = self.white_threshold.get()

        new_data = []
        for item in data:
            # Check if pixel is white/near-white
            if item[0] >= threshold and item[1] >= threshold and item[2] >= threshold:
                # Make transparent
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)

        img.putdata(new_data)
        return img

    def process_image(self):
        """Process the image with current settings and return the result."""
        if not self.original_image:
            return None

        # Start with a copy of the original
        img = self.original_image.copy()

        # Remove background first (before resizing for better AI results)
        if self.remove_background.get():
            if self.bg_removal_method.get() == "ai" and AI_AVAILABLE:
                img = self.remove_background_ai(img)
            else:
                img = self.remove_white_background(img)

        # Calculate target size in pixels
        dpi = self.dpi.get()
        target_width = int(self.width_inches.get() * dpi)
        target_height = int(self.height_inches.get() * dpi)

        # Upscale/resize using Lanczos
        if target_width > 0 and target_height > 0:
            img = img.resize((target_width, target_height), Image.LANCZOS)

        return img

    def update_preview(self):
        """Update the preview canvas with the processed image."""
        if not self.original_image:
            return

        if self.processing:
            return

        self.processing = True

        # Clear edit history when reprocessing
        self.edit_history = []
        self.update_undo_button()

        # Process the image
        self.processed_image = self.process_image()
        if not self.processed_image:
            self.processing = False
            return

        # Get canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width < 10:  # Canvas not yet rendered
            canvas_width = 500
            canvas_height = 400

        # Calculate preview size (fit to canvas)
        img_width, img_height = self.processed_image.size

        scale = min(canvas_width / img_width, canvas_height / img_height, 1.0)
        preview_width = int(img_width * scale)
        preview_height = int(img_height * scale)

        # Create preview image
        preview = self.processed_image.copy()
        preview.thumbnail((preview_width, preview_height), Image.LANCZOS)

        # Create checkerboard background for transparent images
        if self.processed_image.mode == "RGBA":
            checker = self.create_checkerboard(preview.size)
            checker.paste(preview, mask=preview.split()[3])
            preview = checker

        # Convert to PhotoImage
        self.preview_image = ImageTk.PhotoImage(preview)

        # Update canvas
        self.canvas.delete("all")
        self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.preview_image)

        # Update scrollregion
        self.canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))

        # Update info label with processed dimensions
        proc_width, proc_height = self.processed_image.size
        orig_width, orig_height = self.original_image.size
        mode = self.processed_image.mode
        self.info_label.config(
            text=f"Original: {orig_width}x{orig_height}px\n"
                 f"Processed: {proc_width}x{proc_height}px\n"
                 f"Mode: {mode}"
        )

        self.processing = False

    def create_checkerboard(self, size, square_size=10):
        """Create a checkerboard pattern for transparency preview."""
        width, height = size
        checker = Image.new("RGB", (width, height))

        for y in range(0, height, square_size):
            for x in range(0, width, square_size):
                color = (200, 200, 200) if (x // square_size + y // square_size) % 2 == 0 else (255, 255, 255)
                for dy in range(min(square_size, height - y)):
                    for dx in range(min(square_size, width - x)):
                        checker.putpixel((x + dx, y + dy), color)

        return checker

    def export_jpeg(self):
        """Export the processed image as JPEG."""
        if not self.processed_image:
            messagebox.showwarning("Warning", "No image to export. Please load and process an image first.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save as JPEG",
            defaultextension=".jpg",
            filetypes=[("JPEG files", "*.jpg *.jpeg")],
            initialfile=self.get_default_filename("jpg")
        )

        if file_path:
            try:
                # Convert to RGB for JPEG (no transparency support)
                img_to_save = self.processed_image
                if img_to_save.mode == "RGBA":
                    # Create white background
                    background = Image.new("RGB", img_to_save.size, (255, 255, 255))
                    background.paste(img_to_save, mask=img_to_save.split()[3])
                    img_to_save = background
                elif img_to_save.mode != "RGB":
                    img_to_save = img_to_save.convert("RGB")

                img_to_save.save(file_path, "JPEG", quality=95, dpi=(self.dpi.get(), self.dpi.get()))
                messagebox.showinfo("Success", f"Image saved as:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save image:\n{str(e)}")

    def export_tiff(self):
        """Export the processed image as TIFF."""
        if not self.processed_image:
            messagebox.showwarning("Warning", "No image to export. Please load and process an image first.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save as TIFF",
            defaultextension=".tiff",
            filetypes=[("TIFF files", "*.tiff *.tif")],
            initialfile=self.get_default_filename("tiff")
        )

        if file_path:
            try:
                # Save with LZW compression for smaller file size while preserving quality
                self.processed_image.save(file_path, "TIFF",
                                         compression="tiff_lzw",
                                         dpi=(self.dpi.get(), self.dpi.get()))
                messagebox.showinfo("Success", f"Image saved as:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save image:\n{str(e)}")

    def export_both(self):
        """Export the processed image as both JPEG and TIFF."""
        if not self.processed_image:
            messagebox.showwarning("Warning", "No image to export. Please load and process an image first.")
            return

        folder = filedialog.askdirectory(title="Select Output Folder")

        if folder:
            try:
                base_name = self.get_default_filename("")

                # Save JPEG
                jpg_path = os.path.join(folder, base_name + ".jpg")
                img_to_save = self.processed_image
                if img_to_save.mode == "RGBA":
                    background = Image.new("RGB", img_to_save.size, (255, 255, 255))
                    background.paste(img_to_save, mask=img_to_save.split()[3])
                    img_to_save = background
                elif img_to_save.mode != "RGB":
                    img_to_save = img_to_save.convert("RGB")
                img_to_save.save(jpg_path, "JPEG", quality=95, dpi=(self.dpi.get(), self.dpi.get()))

                # Save TIFF with compression
                tiff_path = os.path.join(folder, base_name + ".tiff")
                self.processed_image.save(tiff_path, "TIFF",
                                         compression="tiff_lzw",
                                         dpi=(self.dpi.get(), self.dpi.get()))

                messagebox.showinfo("Success", f"Images saved as:\n{jpg_path}\n{tiff_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save images:\n{str(e)}")

    def get_default_filename(self, extension):
        """Generate a default filename based on the original file."""
        if self.current_file_path:
            base = os.path.splitext(os.path.basename(self.current_file_path))[0]
            return f"{base}_processed{('.' + extension) if extension else ''}"
        return f"processed_image{('.' + extension) if extension else ''}"


def main():
    root = tk.Tk()
    app = ImageProcessorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
