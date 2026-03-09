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
        self.root.title("Ansible Tools")
        self.root.geometry("900x850")
        self.config_file = os.path.expanduser('~/.ansible-tools-gui.json')
        self.cert_dir = os.path.expanduser('~/.ansible-tools')
        
        config = self.load_config()
        self.api_url = tk.StringVar(value=config.get('api_url', os.environ.get('ANSIBLE_TOOLS_API', 'http://localhost:5000')))
        self.api_url.trace_add('write', lambda *args: self.save_config())
        self.model = tk.StringVar(value='codellama:13b')
        self.service = tk.StringVar(value='generate')
        self.dark_mode = tk.BooleanVar(value=config.get('dark_mode', False))
        self.text_color = tk.StringVar(value=config.get('text_color', 'green'))
        self.font_choice = tk.StringVar(value=config.get('font', 'default'))
        
        self.create_menu()
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
        about_text = """Ansible Tools GUI
Version 1.0

A local LLM-powered tool for:
- Converting shell commands to Ansible playbooks
- Explaining Ansible playbooks
- Generating code from descriptions
- Explaining code

Uses Ollama with CodeLlama models (7B, 13B, 34B, 70B)

GitHub: https://github.com/your-repo/ansible-tools
"""
        messagebox.showinfo("About Ansible Tools", about_text)
    
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
        
        # Input frame
        input_frame = ttk.LabelFrame(self.root, text="Input", padding="10")
        input_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.input_text = scrolledtext.ScrolledText(input_frame, height=15, wrap=tk.WORD)
        self.input_text.pack(fill=tk.BOTH, expand=True)
        
        input_buttons = ttk.Frame(input_frame)
        input_buttons.pack(fill=tk.X, pady=5)
        
        ttk.Button(input_buttons, text="Upload File", command=self.upload_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_buttons, text="Upload Multiple Files", command=self.upload_multiple_files).pack(side=tk.LEFT, padx=5)
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
    
    def switch_service(self):
        service = self.service.get()
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

if __name__ == '__main__':
    root = tk.Tk()
    app = AnsibleToolsGUI(root)
    root.mainloop()
