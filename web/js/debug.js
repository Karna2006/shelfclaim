export function createDebugLog(list) {
  const events = [];
  return (source, detail) => {
    const time = new Date();
    events.push({ time: time.toLocaleTimeString(), source, detail });
    if (events.length > 20) events.shift();
    list.replaceChildren(...events.map((event) => {
      const item = document.createElement("li");
      const timestamp = document.createElement("time");
      timestamp.textContent = event.time;
      const message = document.createElement("span");
      message.textContent = `${event.source}: ${event.detail}`;
      item.append(timestamp, message);
      return item;
    }));
  };
}
