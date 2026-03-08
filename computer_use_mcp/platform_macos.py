from __future__ import annotations

from computer_use_mcp.platform_base import DesktopAdapter, DisplayDescriptor


class MacOSAdapter(DesktopAdapter):
    platform_name = "macos"

    def _discover_displays(self) -> dict[str, DisplayDescriptor]:
        import Quartz
        from AppKit import NSScreen

        screens = list(NSScreen.screens())
        if not screens:
            return {}

        frames = [screen.frame() for screen in screens]
        global_top = max(frame.origin.y + frame.size.height for frame in frames)
        main_display_id = int(Quartz.CGMainDisplayID())

        displays: dict[str, DisplayDescriptor] = {}
        secondary_index = 1
        for index, screen in enumerate(screens, start=1):
            device_description = screen.deviceDescription()
            quartz_id = int(device_description["NSScreenNumber"])
            frame = screen.frame()
            scale = float(screen.backingScaleFactor())
            top_left_y = global_top - (frame.origin.y + frame.size.height)
            width_px = int(round(frame.size.width * scale))
            height_px = int(round(frame.size.height * scale))
            origin_x_px = int(round(frame.origin.x * scale))
            origin_y_px = int(round(top_left_y * scale))
            is_primary = quartz_id == main_display_id
            display_id = "primary" if is_primary else f"display-{secondary_index}"
            if not is_primary:
                secondary_index += 1
            name = None
            if hasattr(screen, "localizedName"):
                name = str(screen.localizedName())
            displays[display_id] = DisplayDescriptor(
                id=display_id,
                name=name or f"Display {index}",
                is_primary=is_primary,
                width_px=width_px,
                height_px=height_px,
                logical_width=float(frame.size.width),
                logical_height=float(frame.size.height),
                scale_factor=scale,
                origin_x_px=origin_x_px,
                origin_y_px=origin_y_px,
                logical_origin_x=float(frame.origin.x),
                logical_origin_y=float(top_left_y),
                input_coord_space="logical_points",
            )
        return displays

    def get_active_window_info(self) -> tuple[str | None, str | None]:
        import Quartz
        from AppKit import NSWorkspace

        app = None
        workspace = NSWorkspace.sharedWorkspace()
        frontmost = workspace.frontmostApplication()
        if frontmost is not None:
            app = str(frontmost.localizedName())

        title = None
        try:
            windows = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            for window in windows:
                if window.get("kCGWindowLayer", 0) != 0:
                    continue
                owner = window.get("kCGWindowOwnerName")
                if owner and app and str(owner) != app:
                    continue
                title = window.get("kCGWindowName") or None
                break
        except Exception:
            title = None
        return app, title

    def startup_warnings(self) -> list[str]:
        return [
            "macOS requires Accessibility and Screen Recording permissions for full operation."
        ]
