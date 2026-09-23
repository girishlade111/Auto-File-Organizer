# Auto File Organizer

A desktop application that monitors one or more user-selected folders in real-time and automatically organizes new files into category subfolders based on their file extensions.

## Core Features

### Real-Time Folder Monitoring
- Monitor one or more user-selected folders in real-time (live mode, not scheduled/manual-only)
- Continuously watches for new files appearing in watched folders
- No polling intervals - instant detection of file changes

### Automatic Organization
- When a new file appears, automatically moves it into a category subfolder based on its file extension
- Pre-defined category mappings for common file types (images, documents, videos, audio, archives, etc.)
- Customizable category rules and folder mappings

### System Tray Integration
- Runs continuously in the background via system tray (not a normal open window)
- Minimal UI footprint - stays out of the way until needed
- Double-click tray icon to open/close the main window

### Auto-Start on Windows Boot
- Auto-starts when Windows boots — user should NEVER need to manually open the app again after the first-time install
- Configured via Windows Task Scheduler on first launch
- Optional: user can disable auto-start from the settings menu

### Undo Functionality
- Provides Undo functionality for the last organizing action
- Quickly restore mistakenly moved files to their original location
- Accessible from the system tray menu or main window

### Activity Log
- Maintains an activity log (visible in-app) of what was moved and where
- Logs include: filename, source folder, destination category folder, timestamp
- Scrollable log view in the main window
- Log entries can be cleared manually if desired

## Technology Stack
- Built with Electron/Node.js for cross-platform desktop compatibility
- Real-time file system watching using chokidar or similar library
- Windows Task Scheduler for auto-start configuration
- SQLite or JSON for activity log persistence

## Installation
1. Download the latest installer from the releases page
2. Run the installer
3. On first launch, select folders to monitor
4. Configure category preferences if needed
5. The app will auto-start with Windows and begin monitoring immediately

## Usage
- Open the main window from the system tray icon
- Add/remove folders to monitor via the "Folders" menu
- View the activity log to see organized files
- Use "Undo" to reverse the last action
- Adjust settings as needed

## Configuration
- Add watched folders via the + button
- Remove folders with the trash icon
- Customize file extension to category mappings
- Set auto-start preferences
- Clear activity log from settings