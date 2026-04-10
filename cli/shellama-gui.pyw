#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import urllib.request
import urllib.parse
import json
import os
import threading
import ssl

class AnsibleToolsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("sheLLaMa")
        self.root.geometry("900x850")
        self.config_file = os.path.expanduser('~/.shellama-gui.json')
        self.cert_dir = os.path.expanduser('~/.shellama')
        self.session_tokens = 0
        
        config = self.load_config()
        self.api_url = tk.StringVar(value=config.get('api_url', os.environ.get('SHELLAMA_API', 'http://localhost:5000')))
        self.api_url.trace_add('write', lambda *args: self.save_config())
        self.model = tk.StringVar(value=config.get('model', 'codellama:13b'))
        self.model.trace_add('write', lambda *args: self.save_config())
        self.service = tk.StringVar(value='generate')
        self.dark_mode = tk.BooleanVar(value=config.get('dark_mode', False))
        self.text_color = tk.StringVar(value=config.get('text_color', 'green'))
        self.font_choice = tk.StringVar(value=config.get('font', 'default'))
        self.image_model = tk.StringVar(value=config.get('image_model', 'sd-turbo'))
        
        self.create_menu()
        self.create_widgets()
        if self.dark_mode.get():
            self.toggle_dark_mode()
        self.apply_font()
    
    def get_ssl_config(self):
        """Get SSL certificate paths and create context"""
        ca_cert = os.path.join(self.cert_dir, 'ca-cert.pem')
        client_cert = os.path.join(self.cert_dir, 'client-cert.pem')
        client_key = os.path.join(self.cert_dir, 'client-key.pem')
        
        if os.path.exists(ca_cert) and os.path.exists(client_cert) and os.path.exists(client_key):
            context = ssl.create_default_context(cafile=ca_cert)
            context.load_cert_chain(client_cert, client_key)
            return context
        return None
    
    def load_config(self):
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump({
                    'api_url': self.api_url.get(),
                    'model': self.model.get(),
                    'dark_mode': self.dark_mode.get(),
                    'text_color': self.text_color.get(),
                    'font': self.font_choice.get()
                }, f)
        except:
            pass
    
    def create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self.toggle_and_save)
        settings_menu.add_separator()
        settings_menu.add_radiobutton(label="Green Text", variable=self.text_color, value='green', command=self.toggle_and_save)
        settings_menu.add_radiobutton(label="Amber Text", variable=self.text_color, value='amber', command=self.toggle_and_save)
        settings_menu.add_separator()
        
        font_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="Font", menu=font_menu)
        font_menu.add_radiobutton(label="Default", variable=self.font_choice, value='default', command=self.font_and_save)
        font_menu.add_radiobutton(label="Courier", variable=self.font_choice, value='courier', command=self.font_and_save)
        font_menu.add_radiobutton(label="Consolas", variable=self.font_choice, value='consolas', command=self.font_and_save)
        font_menu.add_radiobutton(label="Terminal", variable=self.font_choice, value='terminal', command=self.font_and_save)
        font_menu.add_radiobutton(label="Fixedsys", variable=self.font_choice, value='fixedsys', command=self.font_and_save)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="View Error Log", command=self.show_error_log)
    
    def show_about(self):
        about_text = """sheLLaMa GUI
Version 1.0

A local LLM-powered tool for:
- Converting shell commands to Ansible playbooks
- Explaining Ansible playbooks
- Generating code from descriptions
- Explaining code

Uses Ollama with CodeLlama models (7B, 13B, 34B, 70B)

GitHub: https://github.com/your-repo/shellama
"""
        messagebox.showinfo("About sheLLaMa", about_text)
    
    def show_error_log(self):
        if not hasattr(self, 'last_error') or not self.last_error:
            messagebox.showinfo("Error Log", "No errors recorded in this session.")
            return
        
        # Create a new window with copyable error text
        error_window = tk.Toplevel(self.root)
        error_window.title("Error Log")
        error_window.geometry("600x400")
        
        error_text = scrolledtext.ScrolledText(error_window, wrap=tk.WORD)
        error_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        error_text.insert(1.0, self.last_error)
        error_text.config(state=tk.NORMAL)  # Make it copyable
        
        ttk.Button(error_window, text="Copy to Clipboard", 
                  command=lambda: self.copy_error_to_clipboard(error_text)).pack(pady=5)
        ttk.Button(error_window, text="Close", command=error_window.destroy).pack(pady=5)
    
    def copy_error_to_clipboard(self, text_widget):
        error_text = text_widget.get(1.0, tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(error_text)
        messagebox.showinfo("Copied", "Error log copied to clipboard!")
    
    def toggle_and_save(self):
        self.toggle_dark_mode()
        self.save_config()
    
    def font_and_save(self):
        self.apply_font()
        self.save_config()
    
    def apply_font(self):
        fonts = {
            'default': ('TkDefaultFont', 10),
            'courier': ('Courier', 10),
            'consolas': ('Consolas', 10),
            'terminal': ('Terminal', 10),
            'fixedsys': ('Fixedsys', 10)
        }
        font = fonts.get(self.font_choice.get(), fonts['default'])
        self.input_text.config(font=font)
        self.output_text.config(font=font)
    
    def toggle_dark_mode(self):
        if self.dark_mode.get():
            bg, fg = '#2b2b2b', '#00ff00' if self.text_color.get() == 'green' else '#ffb000'
            text_bg, button_bg = '#1e1e1e', '#3c3c3c'
        else:
            bg, fg, text_bg, button_bg = '#f0f0f0', '#000000', '#ffffff', '#e0e0e0'
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=bg)
        style.configure('TLabelframe', background=bg, foreground=fg)
        style.configure('TLabelframe.Label', background=bg, foreground=fg)
        style.configure('TLabel', background=bg, foreground=fg)
        style.configure('TButton', background=button_bg, foreground=fg)
        style.configure('TRadiobutton', background=bg, foreground=fg)
        style.configure('TCombobox', fieldbackground=text_bg, background=button_bg, foreground=fg)
        style.configure('TEntry', fieldbackground=text_bg, background=text_bg, foreground=fg)
        style.map('TCombobox', fieldbackground=[('readonly', text_bg)])
        style.map('TCombobox', selectbackground=[('readonly', text_bg)])
        style.map('TCombobox', selectforeground=[('readonly', fg)])
        
        self.root.config(bg=bg)
        self.input_text.config(bg=text_bg, fg=fg, insertbackground=fg)
        self.output_text.config(bg=text_bg, fg=fg, insertbackground=fg)
        
        for widget in self.root.winfo_children():
            self.apply_theme(widget, bg, fg, text_bg)
    
    def apply_theme(self, widget, bg, fg, text_bg):
        try:
            if widget.winfo_class() == 'Entry':
                widget.config(bg=text_bg, fg=fg, insertbackground=fg)
        except:
            pass
        
        for child in widget.winfo_children():
            self.apply_theme(child, bg, fg, text_bg)
    
    def create_widgets(self):
        # Top frame - API URL, Model and Service selection
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        
        ttk.Label(top_frame, text="API URL:").pack(side=tk.LEFT, padx=5)
        api_entry = ttk.Entry(top_frame, textvariable=self.api_url, width=35)
        api_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(top_frame, text="Model:").pack(side=tk.LEFT, padx=5)
        model_combo = ttk.Combobox(top_frame, textvariable=self.model, state='readonly', width=40)
        model_combo['values'] = (
            '--- CodeLlama ---',
            'codellama:7b (Fast, ~4GB RAM)',
            'codellama:13b (Balanced, ~8GB RAM)',
            'codellama:34b (Best Quality, ~20GB RAM)',
            'codellama:70b (Highest Quality, ~40GB RAM)',
            '--- DeepSeek Coder ---',
            'deepseek-coder:1.3b (Tiny, ~1GB RAM)',
            'deepseek-coder:6.7b (Fast, ~4GB RAM)',
            'deepseek-coder:33b (Large, ~20GB RAM)',
            '--- Qwen2.5 Coder ---',
            'qwen2.5-coder:0.5b (Tiny, ~500MB RAM)',
            'qwen2.5-coder:1.5b (Tiny, ~1GB RAM)',
            'qwen2.5-coder:3b (Small, ~2GB RAM)',
            'qwen2.5-coder:7b (Balanced, ~4GB RAM)',
            'qwen2.5-coder:14b (Large, ~8GB RAM)',
            'qwen2.5-coder:32b (Very Large, ~20GB RAM)'
        )
        model_combo.current(2)  # Default to codellama:13b
        model_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(top_frame, text="Image:").pack(side=tk.LEFT, padx=5)
        image_model_combo = ttk.Combobox(top_frame, textvariable=self.image_model, state='readonly', width=20)
        image_model_combo['values'] = ('sd-turbo', 'sdxl-turbo', 'sd-1.5', 'sd-2.1')
        image_model_combo.pack(side=tk.LEFT, padx=5)
        
        # Token counter
        self.token_label = ttk.Label(top_frame, text="Session Tokens: 0")
        self.token_label.pack(side=tk.RIGHT, padx=10)
        
        # Service selection
        service_frame = ttk.Frame(self.root, padding="10")
        service_frame.pack(fill=tk.X)
        
        ttk.Radiobutton(service_frame, text="Shell → Ansible", variable=self.service, 
                       value='generate', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Ansible → Explanation", variable=self.service,
                       value='explain', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Description → Code", variable=self.service,
                       value='generate-code', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Code → Explanation", variable=self.service,
                       value='explain-code', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Chat", variable=self.service,
                       value='chat', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Analyze Files", variable=self.service,
                       value='analyze', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Generate Image", variable=self.service,
                       value='generate-image', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(service_frame, text="Agent", variable=self.service,
                       value='agent', command=self.switch_service).pack(side=tk.LEFT, padx=10)
        
        # Interactive mode checkbox
        self.interactive_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(service_frame, text="Interactive", variable=self.interactive_mode,
                       command=self.toggle_interactive).pack(side=tk.LEFT, padx=10)
        
        # Input frame
        input_frame = ttk.LabelFrame(self.root, text="Input", padding="10")
        input_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.input_text = scrolledtext.ScrolledText(input_frame, height=15, wrap=tk.WORD)
        self.input_text.pack(fill=tk.BOTH, expand=True)
        
        input_buttons = ttk.Frame(input_frame)
        input_buttons.pack(fill=tk.X, pady=5)
        
        ttk.Button(input_buttons, text="Upload File", command=self.upload_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_buttons, text="Upload Multiple Files", command=self.upload_multiple_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_buttons, text="Browse Directory", command=self.browse_directory).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_buttons, text="Generate", command=self.generate).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_buttons, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.status_label = ttk.Label(self.root, text="", foreground="blue")
        self.status_label.pack(fill=tk.X, padx=10)
        
        # Output frame
        output_frame = ttk.LabelFrame(self.root, text="Output", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, height=15, wrap=tk.WORD)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        
        output_buttons = ttk.Frame(output_frame)
        output_buttons.pack(fill=tk.X, pady=5)
        
        ttk.Button(output_buttons, text="Copy", command=self.copy_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(output_buttons, text="Save", command=self.save_output).pack(side=tk.LEFT, padx=5)
        
        # Interactive question frame (hidden by default)
        self.question_frame = ttk.Frame(output_frame)
        self.question_label = ttk.Label(self.question_frame, text="Ask a follow-up question:")
        self.question_label.pack(anchor=tk.W)
        
        question_input_frame = ttk.Frame(self.question_frame)
        question_input_frame.pack(fill=tk.X, pady=5)
        
        self.question_entry = ttk.Entry(question_input_frame)
        self.question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.question_entry.bind('<Return>', lambda e: self.ask_question())
        
        ttk.Button(question_input_frame, text="Ask", command=self.ask_question).pack(side=tk.LEFT)
        
        # Store files context for interactive mode
        self.files_context = None
    
    def switch_service(self):
        service = self.service.get()
        self.files_context = None  # Clear context when switching services
        if service == 'generate':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Shell Commands")
            self.root.children['!labelframe2'].config(text="Ansible Playbook")
        elif service == 'explain':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Ansible Playbook")
            self.root.children['!labelframe2'].config(text="Explanation")
        elif service == 'generate-code':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Code Description")
            self.root.children['!labelframe2'].config(text="Generated Code")
        elif service == 'explain-code':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Code")
            self.root.children['!labelframe2'].config(text="Explanation")
        elif service == 'chat':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Your Message")
            self.root.children['!labelframe2'].config(text="Response")
        elif service == 'analyze':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Files to Analyze")
            self.root.children['!labelframe2'].config(text="Analysis")
        elif service == 'agent':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Files/Directories for Agent Analysis")
            self.root.children['!labelframe2'].config(text="Agent Report")
        elif service == 'generate-image':
            self.input_text.delete(1.0, tk.END)
            self.output_text.delete(1.0, tk.END)
            self.root.children['!labelframe'].config(text="Image Prompt")
            self.root.children['!labelframe2'].config(text="Generated Image")
    
    def toggle_interactive(self):
        """Show/hide interactive question input"""
        if self.interactive_mode.get():
            self.question_frame.pack(fill=tk.X, pady=5)
        else:
            self.question_frame.pack_forget()
            self.files_context = None
    
    def upload_file(self):
        filename = filedialog.askopenfilename(
            title="Select file",
            filetypes=(("Text files", "*.txt"), ("Shell scripts", "*.sh"), 
                      ("YAML files", "*.yml *.yaml"), ("All files", "*.*"))
        )
        if filename:
            with open(filename, 'r') as f:
                content = f.read()
                self.input_text.delete(1.0, tk.END)
                self.input_text.insert(1.0, content)
    
    def upload_multiple_files(self):
        filenames = filedialog.askopenfilenames(
            title="Select files to analyze",
            filetypes=(("All files", "*.*"), ("Python files", "*.py"), 
                      ("YAML files", "*.yml *.yaml"), ("Text files", "*.txt"))
        )
        if filenames:
            self.input_text.delete(1.0, tk.END)
            for filename in filenames:
                self.input_text.insert(tk.END, f"{filename}\n")
    
    def browse_directory(self):
        directory = filedialog.askdirectory(title="Select directory to analyze")
        if directory:
            self.input_text.delete(1.0, tk.END)
            # Recursively find all files
            for root, dirs, files in os.walk(directory):
                for file in files:
                    filepath = os.path.join(root, file)
                    self.input_text.insert(tk.END, f"{filepath}\n")
    
    def get_model_value(self):
        model_str = self.model.get().lower()
        # Skip separator lines
        if model_str.startswith('---'):
            return 'codellama:13b'
        # Extract model name from display string
        if 'deepseek-coder:1.3b' in model_str:
            return 'deepseek-coder:1.3b'
        elif 'deepseek-coder:6.7b' in model_str:
            return 'deepseek-coder:6.7b'
        elif 'deepseek-coder:33b' in model_str:
            return 'deepseek-coder:33b'
        elif 'qwen2.5-coder:0.5b' in model_str:
            return 'qwen2.5-coder:0.5b'
        elif 'qwen2.5-coder:1.5b' in model_str:
            return 'qwen2.5-coder:1.5b'
        elif 'qwen2.5-coder:3b' in model_str:
            return 'qwen2.5-coder:3b'
        elif 'qwen2.5-coder:7b' in model_str:
            return 'qwen2.5-coder:7b'
        elif 'qwen2.5-coder:14b' in model_str:
            return 'qwen2.5-coder:14b'
        elif 'qwen2.5-coder:32b' in model_str:
            return 'qwen2.5-coder:32b'
        elif 'codellama:7b' in model_str:
            return 'codellama:7b'
        elif 'codellama:34b' in model_str:
            return 'codellama:34b'
        elif 'codellama:70b' in model_str:
            return 'codellama:70b'
        else:
            return 'codellama:13b'
    
    def generate(self):
        input_content = self.input_text.get(1.0, tk.END).strip()
        if not input_content:
            messagebox.showwarning("Warning", "Please enter some input")
            return
        
        # Run in thread to avoid blocking UI
        thread = threading.Thread(target=self._generate_thread, args=(input_content,))
        thread.daemon = True
        thread.start()
    
    def _generate_thread(self, input_content):
        try:
            api_url = self.api_url.get()
            
            # Check queue
            self.root.after(0, lambda: self.status_label.config(text="Checking queue..."))
            
            ssl_context = self.get_ssl_config()
            req = urllib.request.Request(f"{api_url}/queue-status")
            with urllib.request.urlopen(req, context=ssl_context) as response:
                queue_data = json.loads(response.read().decode())
            
            if queue_data.get('queue_size', 0) > 0:
                msg = f"Queue position: #{queue_data['queue_size'] + 1} - Generating..."
            else:
                msg = "Generating..."
            
            self.root.after(0, lambda: self.status_label.config(text=msg, foreground="blue"))
            
            # Make API call
            service = self.service.get()
            model = self.get_model_value()
            
            if service == 'generate':
                endpoint = '/generate'
                data = {'commands': input_content, 'model': model}
                output_key = 'playbook'
            elif service == 'explain':
                endpoint = '/explain'
                data = {'playbook': input_content, 'model': model}
                output_key = 'explanation'
            elif service == 'generate-code':
                endpoint = '/generate-code'
                data = {'description': input_content, 'model': model}
                output_key = 'code'
            elif service == 'chat':
                endpoint = '/chat'
                data = {'message': input_content, 'model': model}
                output_key = 'response'
            elif service == 'agent':
                self._agent_thread(input_content, model)
                return
            elif service == 'generate-image':
                self._generate_image_thread(input_content)
                return
            elif service == 'analyze':
                endpoint = '/analyze'
                file_paths = [line.strip() for line in input_content.split('\n') if line.strip()]
                files_data = []
                for path in file_paths:
                    try:
                        with open(path, 'r') as f:
                            files_data.append({'path': path, 'content': f.read()})
                    except Exception as e:
                        files_data.append({'path': path, 'error': str(e)})
                data = {'files': files_data, 'model': model}
                output_key = 'analysis'
                
                # Store context for interactive mode
                if self.interactive_mode.get():
                    self.files_context = files_data
            else:  # explain-code
                endpoint = '/explain-code'
                data = {'code': input_content, 'model': model}
                output_key = 'explanation'
            
            json_data = json.dumps(data).encode('utf-8')
            ssl_context = self.get_ssl_config()
            req = urllib.request.Request(
                f"{api_url}{endpoint}",
                data=json_data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, context=ssl_context) as response:
                result = json.loads(response.read().decode())
            
            if result.get('error'):
                error_msg = f"Error: {result['error']}"
                self.last_error = f"Timestamp: {self.get_timestamp()}\nService: {service}\nModel: {model}\n\n{error_msg}\n\nFull Response:\n{result}"
                self.root.after(0, lambda: self.status_label.config(
                    text=error_msg, foreground="red"))
            else:
                output = result.get(output_key, '')
                self.root.after(0, lambda: self.output_text.delete(1.0, tk.END))
                self.root.after(0, lambda: self.output_text.insert(1.0, output))
                
                # Update session token counter
                tokens = result.get('total_tokens', 0)
                self.session_tokens += tokens
                self.root.after(0, lambda: self.token_label.config(text=f"Session Tokens: {self.session_tokens:,}"))
                
                status_msg = f"Generated in {result['elapsed']}s | Tokens: {result['total_tokens']}"
                if result.get('queue_position'):
                    status_msg += f" | Was #{result['queue_position']} in queue"
                
                self.root.after(0, lambda: self.status_label.config(
                    text=status_msg, foreground="green"))
        
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.last_error = f"Timestamp: {self.get_timestamp()}\nException: {type(e).__name__}\n\n{str(e)}"
            self.root.after(0, lambda: self.status_label.config(
                text=error_msg, foreground="red"))
    
    def _api_call(self, endpoint, data):
        """Make an API call and return the result dict."""
        json_data = json.dumps(data).encode('utf-8')
        ssl_context = self.get_ssl_config()
        req = urllib.request.Request(
            f"{self.api_url.get()}{endpoint}",
            data=json_data,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, context=ssl_context) as response:
            return json.loads(response.read().decode())

    def _agent_append(self, text):
        """Append text to output and scroll to end."""
        self.root.after(0, lambda: self.output_text.insert(tk.END, text))
        self.root.after(0, lambda: self.output_text.see(tk.END))

    def _agent_thread(self, input_content, model, max_rounds=5):
        """Agentic multi-round analysis with live output."""
        try:
            # Read files
            file_paths = [line.strip() for line in input_content.split('\n') if line.strip()]
            files_data = []
            for path in file_paths:
                if os.path.isdir(path):
                    for root, dirs, files in os.walk(path):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                with open(fp, 'r') as fh:
                                    files_data.append({'path': fp, 'content': fh.read()})
                            except Exception as e:
                                pass
                else:
                    try:
                        with open(path, 'r') as fh:
                            files_data.append({'path': path, 'content': fh.read()})
                    except Exception as e:
                        pass

            if not files_data:
                self.root.after(0, lambda: self.status_label.config(text="Error: No readable files found", foreground="red"))
                return

            files_context = "\n\n".join([f"=== {f['path']} ===\n{f['content']}" for f in files_data])
            file_list = "\n".join([f"  - {f['path']}" for f in files_data])
            total_tokens = 0
            total_elapsed = 0
            findings = []

            self.root.after(0, lambda: self.output_text.delete(1.0, tk.END))

            # Round 1
            self.root.after(0, lambda: self.status_label.config(
                text=f"[Agent] Round 1/{max_rounds}: Initial analysis of {len(files_data)} file(s)...", foreground="blue"))
            self._agent_append(f"═══ Round 1/{max_rounds}: Initial Analysis ═══\n\n")

            result = self._api_call('/chat', {'message': f"""Analyze these files. Provide:
1. Overview of what this codebase/project does
2. File relationships and dependencies
3. Key issues, bugs, or security concerns
4. Areas that need deeper investigation

Files:
{files_context}""", 'model': model})

            if result.get('error'):
                self.root.after(0, lambda: self.status_label.config(text=f"Error: {result['error']}", foreground="red"))
                return

            findings.append(result['response'])
            total_tokens += result.get('total_tokens', 0)
            total_elapsed += result.get('elapsed', 0)
            self._agent_append(f"{result['response']}\n\n[{result['elapsed']}s | {result.get('total_tokens', 0)} tokens]\n\n")

            # Rounds 2+
            for round_num in range(2, max_rounds + 1):
                self.root.after(0, lambda rn=round_num: self.status_label.config(
                    text=f"[Agent] Round {rn}/{max_rounds}: Investigating...", foreground="blue"))
                self._agent_append(f"═══ Round {round_num}/{max_rounds}: Deep Dive ═══\n\n")

                result = self._api_call('/chat', {'message': f"""You are analyzing a codebase. Here are the files:
{file_list}

Your analysis so far:
{chr(10).join(findings)}

Based on your analysis so far, what is the most important thing to investigate next? Pick ONE specific topic and analyze it in depth using the file contents below. Focus on something you haven't fully covered yet — such as error handling, security, performance, code quality, missing features, or architectural issues.

If you believe the analysis is thorough enough, respond with exactly "ANALYSIS COMPLETE" on the first line.

Files:
{files_context}""", 'model': model})

                if result.get('error'):
                    self._agent_append(f"Error: {result['error']}\n\n")
                    break

                response = result['response']
                total_tokens += result.get('total_tokens', 0)
                total_elapsed += result.get('elapsed', 0)

                if response.strip().startswith('ANALYSIS COMPLETE'):
                    self._agent_append(f"Agent determined analysis is complete.\n\n")
                    break

                findings.append(response)
                self._agent_append(f"{response}\n\n[{result['elapsed']}s | {result.get('total_tokens', 0)} tokens]\n\n")

            # Final consolidation
            self.root.after(0, lambda: self.status_label.config(
                text="[Agent] Generating final report...", foreground="blue"))
            self._agent_append(f"═══ Final Consolidated Report ═══\n\n")

            report = self._api_call('/chat', {'message': f"""You performed a multi-round analysis of a codebase. Consolidate all findings below into a single, well-organized final report. Remove duplicates, organize by topic, and prioritize the most important findings.

Findings from {len(findings)} rounds of analysis:

{chr(10).join([f"--- Round {i+1} ---{chr(10)}{f}" for i, f in enumerate(findings)])}

Write the final consolidated report now.""", 'model': model})

            total_tokens += report.get('total_tokens', 0)
            total_elapsed += report.get('elapsed', 0)

            if report.get('error'):
                self._agent_append(f"Error generating report: {report['error']}\n")
            else:
                self._agent_append(f"{report['response']}\n")

            self.session_tokens += total_tokens
            self.root.after(0, lambda: self.token_label.config(text=f"Session Tokens: {self.session_tokens:,}"))
            self.root.after(0, lambda: self.status_label.config(
                text=f"[Agent] Done: {len(findings)} rounds, {total_elapsed:.1f}s, {total_tokens:,} tokens", foreground="green"))

            # Store context for interactive follow-ups
            if self.interactive_mode.get():
                self.files_context = files_data

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.last_error = f"Timestamp: {self.get_timestamp()}\nException: {type(e).__name__}\n\n{str(e)}"
            self.root.after(0, lambda: self.status_label.config(text=error_msg, foreground="red"))

    def _generate_image_thread(self, prompt):
        """Generate an image and display it in the output area."""
        try:
            import base64
            import tempfile
            
            self.root.after(0, lambda: self.status_label.config(text="Generating image (this may take several minutes on CPU)...", foreground="blue"))
            
            image_model = self.image_model.get()
            steps = 4 if 'turbo' in image_model else 20
            
            data = {'prompt': prompt, 'image_model': image_model, 'steps': steps, 'width': 512, 'height': 512}
            result = self._api_call('/generate-image', data)
            
            if result.get('error'):
                self.last_error = f"Image generation error: {result['error']}"
                self.root.after(0, lambda: self.status_label.config(text=f"Error: {result['error']}", foreground="red"))
                return
            
            # Save image to temp file and show path
            image_data = base64.b64decode(result['image'])
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False, prefix='shellama-')
            tmp.write(image_data)
            tmp.close()
            
            self.root.after(0, lambda: self.output_text.delete(1.0, tk.END))
            self.root.after(0, lambda: self.output_text.insert(1.0,
                f"Image saved to: {tmp.name}\n\n"
                f"Model: {result.get('model', image_model)}\n"
                f"Prompt: {prompt}\n"
                f"Steps: {result.get('steps', steps)}\n"
                f"Size: {result.get('width', 512)}x{result.get('height', 512)}\n"
                f"Time: {result['elapsed']}s"))
            
            self.root.after(0, lambda: self.status_label.config(
                text=f"Image generated in {result['elapsed']}s — saved to {tmp.name}", foreground="green"))
            
        except Exception as e:
            self.last_error = f"Exception: {str(e)}"
            self.root.after(0, lambda: self.status_label.config(text=f"Error: {str(e)}", foreground="red"))

    def get_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def copy_output(self):
        output = self.output_text.get(1.0, tk.END).strip()
        if output:
            self.root.clipboard_clear()
            self.root.clipboard_append(output)
            self.status_label.config(text="Copied to clipboard!", foreground="green")
    
    def save_output(self):
        output = self.output_text.get(1.0, tk.END).strip()
        if not output:
            messagebox.showwarning("Warning", "No output to save")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".yml",
            filetypes=(("YAML files", "*.yml"), ("Text files", "*.txt"), ("All files", "*.*"))
        )
        if filename:
            with open(filename, 'w') as f:
                f.write(output)
            self.status_label.config(text=f"Saved to {filename}", foreground="green")
    
    def clear_all(self):
        self.input_text.delete(1.0, tk.END)
        self.output_text.delete(1.0, tk.END)
        self.status_label.config(text="")
        self.files_context = None
        self.question_entry.delete(0, tk.END)
    
    def ask_question(self):
        """Ask a follow-up question in interactive mode"""
        if not self.files_context:
            messagebox.showwarning("Warning", "No files analyzed yet. Run analysis first with Interactive mode enabled.")
            return
        
        question = self.question_entry.get().strip()
        if not question:
            return
        
        # Run in thread
        thread = threading.Thread(target=self._ask_question_thread, args=(question,))
        thread.daemon = True
        thread.start()
    
    def _ask_question_thread(self, question):
        try:
            self.root.after(0, lambda: self.status_label.config(text="Asking question...", foreground="blue"))
            
            # Build context with files
            files_context = "\n\n".join([f"=== {f['path']} ===\n{f['content']}" for f in self.files_context if 'content' in f])
            full_message = f"I have these files:\n\n{files_context}\n\nQuestion: {question}"
            
            model = self.get_model_value()
            ssl_context = self.get_ssl_config()
            
            data = {'message': full_message, 'model': model}
            json_data = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(
                f"{self.api_url.get()}/chat",
                data=json_data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, context=ssl_context) as response:
                result = json.loads(response.read().decode())
            
            if result.get('error'):
                error_msg = f"Error: {result['error']}"
                self.root.after(0, lambda: self.status_label.config(text=error_msg, foreground="red"))
            else:
                # Append Q&A to output
                qa_text = f"\n\n--- Question ---\n{question}\n\n--- Answer ---\n{result['response']}"
                self.root.after(0, lambda: self.output_text.insert(tk.END, qa_text))
                self.root.after(0, lambda: self.output_text.see(tk.END))
                self.root.after(0, lambda: self.question_entry.delete(0, tk.END))
                
                # Update session token counter
                tokens = result.get('total_tokens', 0)
                self.session_tokens += tokens
                self.root.after(0, lambda: self.token_label.config(text=f"Session Tokens: {self.session_tokens:,}"))
                
                status_msg = f"Answered in {result['elapsed']}s | Tokens: {result['total_tokens']}"
                self.root.after(0, lambda: self.status_label.config(text=status_msg, foreground="green"))
        
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.root.after(0, lambda: self.status_label.config(text=error_msg, foreground="red"))

if __name__ == '__main__':
    root = tk.Tk()
    app = AnsibleToolsGUI(root)
    root.mainloop()
