//! Keep render workers and Chromium children inside the desktop process lifetime.
use std::io;
use std::process::{Child, Command};

#[cfg(unix)]
pub fn configure(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}

#[cfg(windows)]
pub fn configure(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    // Assign the job before PyInstaller can spawn its actual Python process.
    command.creation_flags(0x08000004); // CREATE_NO_WINDOW | CREATE_SUSPENDED
}

#[cfg(unix)]
pub struct ProcessTree {
    group: u32,
    stopped: std::sync::atomic::AtomicBool,
}

#[cfg(unix)]
impl ProcessTree {
    pub fn attach(child: &Child) -> io::Result<Self> {
        Ok(Self {
            group: child.id(),
            stopped: std::sync::atomic::AtomicBool::new(false),
        })
    }

    pub fn terminate(&self) {
        if self.stopped.swap(true, std::sync::atomic::Ordering::AcqRel) {
            return;
        }
        unsafe extern "C" {
            fn kill(pid: i32, signal: i32) -> i32;
        }
        // Playwright deliberately starts Chromium in its own process group on
        // Unix. Snapshot descendants before killing their parents, including
        // members of our original group after the sidecar leader has exited.
        let groups = descendant_groups(self.group);
        for group in groups {
            unsafe { kill(-(group as i32), 9) };
        }
        unsafe { kill(-(self.group as i32), 9) };
    }
}

#[cfg(unix)]
impl Drop for ProcessTree {
    fn drop(&mut self) {
        self.terminate();
    }
}

#[cfg(unix)]
fn descendant_groups(root: u32) -> Vec<u32> {
    use std::collections::HashSet;
    let output = match Command::new("/bin/ps")
        .args(["-axo", "pid=,ppid=,pgid="])
        .output()
    {
        Ok(output) if output.status.success() => output,
        _ => return Vec::new(),
    };
    let rows: Vec<(u32, u32, u32)> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| {
            let values: Vec<u32> = line
                .split_whitespace()
                .filter_map(|value| value.parse().ok())
                .collect();
            (values.len() == 3).then(|| (values[0], values[1], values[2]))
        })
        .collect();
    let mut owned: HashSet<u32> = rows
        .iter()
        .filter(|(_, _, group)| *group == root)
        .map(|(pid, _, _)| *pid)
        .collect();
    loop {
        let before = owned.len();
        for (pid, parent, _) in &rows {
            if owned.contains(parent) {
                owned.insert(*pid);
            }
        }
        if before == owned.len() {
            break;
        }
    }
    rows.iter()
        .filter(|(pid, _, group)| owned.contains(pid) && *group != root && *group > 1)
        .map(|(_, _, group)| *group)
        .collect::<HashSet<_>>()
        .into_iter()
        .collect()
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::ffi::c_void;
    use std::os::windows::io::AsRawHandle;

    type Handle = *mut c_void;

    #[repr(C)]
    #[derive(Default)]
    struct BasicLimit {
        per_process_user_time: i64,
        per_job_user_time: i64,
        flags: u32,
        minimum_working_set: usize,
        maximum_working_set: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    #[derive(Default)]
    struct IoCounters {
        values: [u64; 6],
    }

    #[repr(C)]
    #[derive(Default)]
    struct ExtendedLimit {
        basic: BasicLimit,
        io: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    #[repr(C)]
    struct ThreadEntry {
        size: u32,
        usage: u32,
        thread_id: u32,
        process_id: u32,
        base_priority: i32,
        delta_priority: i32,
        flags: u32,
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(job: Handle, class: u32, info: *const c_void, size: u32) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn TerminateJobObject(job: Handle, exit_code: u32) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn CreateToolhelp32Snapshot(flags: u32, process_id: u32) -> Handle;
        fn Thread32First(snapshot: Handle, entry: *mut ThreadEntry) -> i32;
        fn Thread32Next(snapshot: Handle, entry: *mut ThreadEntry) -> i32;
        fn OpenThread(access: u32, inherit: i32, thread_id: u32) -> Handle;
        fn ResumeThread(thread: Handle) -> u32;
    }

    pub struct ProcessTree(Handle);
    // A job handle may be used across threads; access does not mutate Rust data.
    unsafe impl Send for ProcessTree {}
    unsafe impl Sync for ProcessTree {}

    impl ProcessTree {
        pub fn attach(child: &Child) -> io::Result<Self> {
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let tree = Self(handle);
            let limits = ExtendedLimit {
                basic: BasicLimit {
                    flags: 0x00002000, // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    ..Default::default()
                },
                ..Default::default()
            };
            let configured = unsafe {
                SetInformationJobObject(
                    handle,
                    9, // JobObjectExtendedLimitInformation
                    &limits as *const _ as *const c_void,
                    std::mem::size_of::<ExtendedLimit>() as u32,
                )
            };
            if configured == 0
                || unsafe { AssignProcessToJobObject(handle, child.as_raw_handle()) } == 0
            {
                return Err(io::Error::last_os_error());
            }
            resume_child(child.id())?;
            Ok(tree)
        }

        pub fn terminate(&self) {
            unsafe { TerminateJobObject(self.0, 1) };
        }
    }

    fn resume_child(process_id: u32) -> io::Result<()> {
        let snapshot = unsafe { CreateToolhelp32Snapshot(4, 0) }; // TH32CS_SNAPTHREAD
        if snapshot as isize == -1 {
            return Err(io::Error::last_os_error());
        }
        let mut entry = ThreadEntry {
            size: std::mem::size_of::<ThreadEntry>() as u32,
            usage: 0,
            thread_id: 0,
            process_id: 0,
            base_priority: 0,
            delta_priority: 0,
            flags: 0,
        };
        let mut found = unsafe { Thread32First(snapshot, &mut entry) } != 0;
        let mut result = Err(io::Error::new(
            io::ErrorKind::NotFound,
            "Rendering engine startup thread was not found.",
        ));
        while found {
            if entry.process_id == process_id {
                let thread = unsafe { OpenThread(2, 0, entry.thread_id) }; // THREAD_SUSPEND_RESUME
                result = if thread.is_null() {
                    Err(io::Error::last_os_error())
                } else {
                    let resumed = unsafe { ResumeThread(thread) };
                    let outcome = if resumed == u32::MAX {
                        Err(io::Error::last_os_error())
                    } else {
                        Ok(())
                    };
                    unsafe { CloseHandle(thread) };
                    outcome
                };
                break;
            }
            found = unsafe { Thread32Next(snapshot, &mut entry) } != 0;
        }
        unsafe { CloseHandle(snapshot) };
        result
    }

    impl Drop for ProcessTree {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }
}

#[cfg(windows)]
pub use windows::ProcessTree;

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::process::Stdio;
    use std::time::{Duration, Instant};

    #[test]
    fn stopping_tree_ends_inherited_pipe_after_leader_exits() {
        let mut command = Command::new("sh");
        command
            .args(["-c", "sleep 30 & echo ready"])
            .stdout(Stdio::piped());
        configure(&mut command);
        let mut child = command.spawn().unwrap();
        let tree = ProcessTree::attach(&child).unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        output.read_line(&mut line).unwrap();
        assert_eq!(line, "ready\n");
        child.wait().unwrap();
        // The background child holds stdout open after sh has exited.
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || sender.send(output.read_line(&mut String::new())).unwrap());
        assert!(receiver.recv_timeout(Duration::from_millis(50)).is_err());
        let started = Instant::now();
        tree.terminate();
        assert_eq!(
            receiver
                .recv_timeout(Duration::from_secs(2))
                .unwrap()
                .unwrap(),
            0
        );
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn stopping_tree_also_ends_a_detached_browser_group() {
        let mut command = Command::new("sh");
        command
            .args(["-c", "setsid sh -c 'echo detached-ready; sleep 30' & wait"])
            .stdout(Stdio::piped());
        configure(&mut command);
        let mut child = command.spawn().unwrap();
        let tree = ProcessTree::attach(&child).unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        output.read_line(&mut line).unwrap();
        assert_eq!(line, "detached-ready\n");
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || sender.send(output.read_line(&mut String::new())).unwrap());
        assert!(receiver.recv_timeout(Duration::from_millis(50)).is_err());
        tree.terminate();
        assert_eq!(
            receiver
                .recv_timeout(Duration::from_secs(2))
                .unwrap()
                .unwrap(),
            0
        );
        child.wait().unwrap();
    }
}

#[cfg(all(test, windows))]
mod windows_tests {
    use super::*;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::process::Stdio;
    use std::time::Duration;

    // A subprocess-only fixture keeps the test independent of PowerShell/CMD
    // quoting and proves the job includes descendants after its leader exits.
    #[test]
    fn child_fixture() {
        match std::env::var("MARDAS_PROCESS_TREE_TEST_ROLE").as_deref() {
            Ok("leader") => {
                let mut input = String::new();
                std::io::stdin().read_line(&mut input).unwrap();
                let mut command = fixture_command("leaf");
                command.stdin(Stdio::null());
                let _child = command.spawn().unwrap();
                println!("TREE_READY");
            }
            Ok("leaf") => std::thread::sleep(Duration::from_secs(30)),
            Ok("cleanup") => std::thread::sleep(Duration::from_millis(50)),
            _ => {}
        }
    }

    fn fixture_command(role: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "process_tree::windows_tests::child_fixture",
                "--nocapture",
            ])
            .env("MARDAS_PROCESS_TREE_TEST_ROLE", role);
        // The leaf already inherits its leader's job; no second suspension.
        if role == "leaf" {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        } else {
            configure(&mut command);
        }
        command
    }

    #[test]
    fn job_terminates_descendant_after_its_parent_has_exited() {
        let mut command = fixture_command("leader");
        command.stdin(Stdio::piped()).stdout(Stdio::piped());
        let mut child = command.spawn().unwrap();
        let tree = ProcessTree::attach(&child).unwrap();
        child.stdin.take().unwrap().write_all(b"go\n").unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        loop {
            let mut line = String::new();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            if line.trim() == "TREE_READY" {
                break;
            }
        }
        assert!(child.wait().unwrap().success());
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || sender.send(output.read_to_end(&mut Vec::new())).unwrap());
        assert!(receiver.recv_timeout(Duration::from_millis(50)).is_err());
        tree.terminate();
        assert!(receiver
            .recv_timeout(Duration::from_secs(2))
            .unwrap()
            .is_ok());
    }
}
